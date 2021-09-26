import requests
import json
from config import DISCORD_TOKEN, APP_ID, GUILD_IDS


base_url = "https://discord.com/api/v8"
url_global = f"https://discord.com/api/v8/applications/{APP_ID}/commands"

_commands = [
    {
        "name": "roll",
        "description": "roll between 1 - 100, or the max value provided",
        "options": [{"name": "max", "description": "max to roll", "type": 4, "required": False}],
    },
    {
        "name": "8ball",
        "description": "Ask the magic 8-ball for guidance",
        "options": [
            {
                "name": "question",
                "description": "what would you like to ask the 8-ball",
                "type": 3,
                "required": True,
            }
        ],
    },
    {
        "name": "stock",
        "description": "stock info",
        "options": [
            {
                "name": "ticker",
                "description": "Get the current stock price",
                "type": 3,
                "required": True,
            }
        ],
    },
]

add_song = {
    "name": "add",
    "description": "Add a song to the playlist",
    "options": [
        {
            "name": "song",
            "description": "the song you want to add to the playlist",
            "type": 3,
            "required": True,
        },
    ],
}

playlist = {
    "name": "playlist",
    "description": "List songs in the playlist",
}

play = {
    "name": "play",
    "description": "Start playing from the playlist",
}
stop = {
    "name": "stop",
    "description": "Stop playing from the playlist",
}
pause = {
    "name": "pause",
    "description": "Pause/Resume the current playing track",
}
volume = {
    "name": "volume",
    "description": "Change the volume of player, leave blank to get current volume",
    "options": [{"name": "volume", "description": "Volume [1-100] (ex: 40%)", "type": 3}],
}


leave = {
    "name": "leave",
    "description": "Ask RoosterBot to leave the voice channel",
}
join = {
    "name": "join",
    "description": "Ask RoosterBot to join you in a voice channel",
}

skip = {
    "name": "skip",
    "description": "Skip the current track",
}

remove = {
    "name": "remove",
    "description": "Remove an item from the playlist",
    "options": [{
        "name": "track_number",
        "description": "Number of the track to remove",
        "type": 4,
        "required": False
    }]
}

commands = [skip]

# For authorization, you can use either your bot token
headers = {"Authorization": f"Bot {DISCORD_TOKEN}"}


def rate_limit_headers(headers: dict) -> dict:
    return {header: headers[header] for header in headers.keys() if "x-rate" in header}


def register_one(command: dict, update=False, id: int = None) -> dict:
    if update:
        r = requests.patch(f"{url_global}/{id}", headers=headers, json=command)
    else:
        r = requests.post(url_global, headers=headers, json=command)
    print(r.headers)
    print(rate_limit_headers(r.headers))
    return r.json()


def register_all(commands: list[dict], update: bool = False) -> list:
    responses = []
    for item in commands:
        r = register_one(item, update)
        responses.append(r)
    return responses


def register_at_all_guilds(command: dict):
    for guild in GUILD_IDS:
        register_at_guild(command, guild)


def register_at_guild(command: dict, guild: int) -> dict:
    url = f"{base_url}/applications/{APP_ID}/guilds/{guild}/commands"
    r = requests.post(url, headers=headers, json=command)
    print(rate_limit_headers(r.headers))
    return r.json()


def get_global_commands():
    r = requests.get(url_global, headers=headers)
    print(rate_limit_headers(r.headers))
    return r.json()


if __name__ == "__main__":
    print(register_one(add_song))
