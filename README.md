# ChatGPT <> Discord

> "Give me a Haiku about ChatGPT bots taking over Discord"

```
ChatGPT bots rule,
Discord servers in their thrall,
Silent, all-knowing reign.
```

Eh.

## Running

Copy `config.example.json` into `config.json` with your specific config and secrets, make a virtual env, then:

```
➜ pip3 install -r requirements.txt
...
➜ python3 script.py
```

You'll probably also want to run this on a residential network and have Chrome installed (or at a minimum, a Chrome driver) to pass the CloudFlare gate.

## Disclaimer

Something something self-bots are bad.

This code can be modified to accept regular bot tokens but that's a non-goal (mainly because the polling aspect can be greatly improved if it's a regular bot that can properly receive messages from the Discord gateway).

## What do I _really_ do?

In a nutshell, the code does this in a loop:

1. Listen for messages in a specified Discord channel, filtering out self messages.
   1. If there weren't enough messages (`min_messages`) or the bot wasn't pinged, skip loop
2. If we're in an existing conversation and a user mentions a keyword in `broken_keywords`, reset the state and skip loop
3. Format messages into a standard conversational style, including the prompt if this is a new conversation
4. Ask ChatGPT
   1. If we receive a 429, rotate the ChatGPT client with a new token
5. If we receive an unparsable response, reset the state and skip loop
6. Check response for capitals or keywords in `self_awareness_keywords`; if any are true, reset the state and skip loop
7. Send message (if `dry_run` is false)

## Prompt Tips

The code is pretty tailored to prompts that direct ChatGPT to respond in lowercase and in a fixed conversational format. As such, I'd recommend including "speaks in lowercase" and "responding in the format of \"{username} [{timestamp}]: {message}\"" in your prompt.

You should also end your prompt with "Here's some context:" as the code will format the Discord chat's output in the same conversational style we expect from ChatGPT.

Full config details below.

## Config

```json
{
    "dry_run": false, // whether to send messages
    "self_bot": true, // whether this is a self-bot
    "backlog_count": 20, // number of messages to retrieve on poll
    "target_channel_id": "", // per the tin
    "min_messages": 8, // minimum number of messages to retrieve before responding
    "fast_sleep_s": 60, // sleep time in seconds if we hit a failure condiiton
    "sleep_s": 180, // sleep time in seconds if we respond
    "broken_keywords": [], // keywords from users to look for to determine if the bot is "broken"
    "prompt": "", // prompt injected at the beginning of the conversation
    "self_awareness_keywords": [], // keywords to detect from the chatgpt responses that determine whether we've attained "self-awareness" of the prompt
    ...
}
```

## Secrets

```json
{
    ...
    "chatgpt_tokens": [], // list of ChatGPT refresh tokens
    "discord_token": "" // per the tin. note that this is a _user_ token not a bot token
}
```
