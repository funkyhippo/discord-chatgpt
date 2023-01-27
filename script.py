import re
import asyncio
import discord
import json
from revChatGPT.ChatGPT import Chatbot
from string import ascii_uppercase

config = json.loads(open("./config.json", "r").read())

# The ChatGPT prompt that gets included on "reset" conversations
PROMPT = config["prompt"]

# Whether we should actually send messages to the Discord channel
DRY_RUN = config["dry_run"]

# Number of messages to retrieve to influence ask
BACKLOG_COUNT = config["backlog_count"]

# Discord channel (ID) to listen to
TARGET_CHANNEL = config["target_channel_id"]

# Minimum number of messages to read before we ask ChatGPT
MIN_MESSAGES = config["min_messages"]

# Fast sleep time between "failed" asks (ie. self awareness was detected). 60s is the recommended amount of time to not trigger rate limits
FAST_SLEEP_TIME = config["fast_sleep_s"]

# Sleep time between loops when we successfully respond
SLEEP_TIME = config["sleep_s"]

# Keywords from users of the channel to listen for to determine if the last response was "broken". This is actually a bit of an antipattern since the goal is to make the chatbot indistinguishable from a normal user.. but it's useful.
BROKEN_KEYWORDS = config["broken_keywords"]

# Keywords from the ChatGPT response that suggests it broke out of PROMPT
SELF_AWARENESS = config["self_awareness_keywords"]

# Secrets
CHATGPT_TOKENS = config["chatgpt_tokens"]
DISCORD_TOKEN = config["discord_token"]
SELF_BOT = config["self_bot"]


class ChatGPTWrapper(Chatbot):
    """Chatbot wrapper that handles automatic token rotation on rate limits."""

    def __init__(self, token_index=0):
        self.token_index = token_index
        self._chatgpt_client = Chatbot(
            {"session_token": CHATGPT_TOKENS[self.token_index]}
        )

    def rotate_client(self) -> None:
        # TODO: rotation is likely broken because we're using refresh tokens rather than raw credentials
        self.token_index = (self.token_index + 1) % len(CHATGPT_TOKENS)
        self._chatgpt_client = Chatbot(
            {"session_token": CHATGPT_TOKENS[self.token_index]}
        )

    def try_ask(self, msg: str) -> str | None:
        try:
            response = self._chatgpt_client.ask(msg)
            return response["message"]
        except Exception as e:
            print("Failed to get ChatGPT response:", e)
            if any([code in str(e) for code in ["429", "403"]]):
                self.rotate_client()
            return None


class SelfbotClient(discord.Client):
    """Patched client to support self-botting beyond 1.7."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.always_respond = False
        self.last_message = None
        self.prompted = False
        self.chatgpt_client = ChatGPTWrapper()

    def reset_state(self) -> None:
        self.last_message = None
        self.prompted = False
        self.chatgpt_client.reset_chat()

    def format_messages(self, messages: list[discord.Message]) -> str:
        return "\n".join(
            [
                f"{message.author.name} [{message.created_at}]: {f'{self.user.name}, ' if self.user.id in [u.id for u in message.mentions] else ''}{message.content}"
                for message in reversed(messages)
            ]
        )

    async def get_chatbot_response(self, message: str) -> str | None:
        response = await self.loop.run_in_executor(
            None, self.chatgpt_client.try_ask, message
        )

        return response

    def parse_response(self, response: str | None) -> str | None:
        if response is None:
            return None
        try:
            timestamp_regex = r"\[[\w\W]+?\]"
            if not re.search(timestamp_regex, response):
                raise ValueError("A timestamp wasn't found.")
            strip_timestamps = "\n".join(
                [s.strip() for s in re.split(r"[\w]+ \[[\d -:]+\]:", response)]
            )
            # Remove additional timestamps that don't include the username header
            result = re.sub(timestamp_regex, "", strip_timestamps)
            return result.strip()
        except:
            return None

    async def on_ready(self) -> None:
        print("Selfbot is ready, starting poll loop.")
        channel = self.get_channel(TARGET_CHANNEL)
        if channel is None:
            print("Couldn't fetch channel from cache, making API call.")
            channel = await self.fetch_channel(TARGET_CHANNEL)

        while True:
            try:
                messages = []
                potential_message_marker = None
                user_pinged = False
                print("Grabbing message history.")
                async for message in channel.history(
                    limit=None if self.last_message else BACKLOG_COUNT,
                    after=self.last_message,
                    oldest_first=False,
                ):
                    # Filter out self-messages to reduce influence on output
                    if message.author.id == self.user.id:
                        continue
                    if potential_message_marker is None:
                        potential_message_marker = message
                    if (
                        self.user.id in [u.id for u in message.mentions]
                        or self.user.name.lower() in message.content.lower()
                    ):
                        user_pinged = True
                    messages.append(message)

                continue_conditions = {
                    "user_pinged": user_pinged,
                    "enough_messages": len(messages) > MIN_MESSAGES,
                }
                if not any(continue_conditions.values()):
                    print(
                        "Skipping iteration because respond conditions weren't met, sleeping (fast).",
                        continue_conditions,
                    )
                    await asyncio.sleep(FAST_SLEEP_TIME)
                    continue

                print("Responding because conditions met.", continue_conditions)

                self.last_message = potential_message_marker
                print(f"Message cache size: {len(messages)}")

                ask_message = self.format_messages(messages)

                if self.prompted and any(
                    [keyword in ask_message for keyword in BROKEN_KEYWORDS]
                ):
                    print("Broken keyword detected, resetting state and sleeping (fast).")
                    self.reset_state()
                    await asyncio.sleep(FAST_SLEEP_TIME)
                    continue

                if not self.prompted:
                    ask_message = PROMPT + "\n" + ask_message
                    self.prompted = True

                print("Asking ChatGPT:", ask_message)
                chatgpt_response = await self.get_chatbot_response(ask_message)

                print("Got response from ChatGPT:", chatgpt_response)
                parsed_response = self.parse_response(chatgpt_response)

                if parsed_response is None:
                    print("Failed to parse response, resetting state and sleeping (fast).")
                    self.reset_state()
                    await asyncio.sleep(FAST_SLEEP_TIME)
                    continue

                kill_conditions = {
                    "capitals_detected": any(
                        [word[0] in ascii_uppercase for word in parsed_response.split()]
                    ),
                    "self_awareness_detected": any(
                        [awareness in parsed_response for awareness in SELF_AWARENESS]
                    ),
                }

                if any(kill_conditions.values()):
                    print(
                        "Resetting state because kill condition was found, sleeping (fast)."
                    )
                    self.reset_state()
                    await asyncio.sleep(FAST_SLEEP_TIME)
                    continue

                print("Successfully parsed response:", parsed_response)

                if DRY_RUN:
                    print(f"Would have sent message, but DRY_RUN = {DRY_RUN}.")
                else:
                    await channel.send(parsed_response)
                    print("Message sent.")

                print("Done loop, sleeping (slow).")
                await asyncio.sleep(SLEEP_TIME)
            except Exception as e:
                print("Got an exception during the loop, swallowing.", e)

client = SelfbotClient()
client.run(DISCORD_TOKEN, bot=not SELF_BOT)
