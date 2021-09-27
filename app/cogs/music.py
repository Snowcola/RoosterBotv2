from dataclasses import dataclass
import typing
from discord import Embed, VoiceChannel, VoiceClient, FFmpegOpusAudio, FFmpegPCMAudio, PCMVolumeTransformer
from discord.ext.commands import Bot, Cog
from typing import Union
from discord_slash import cog_ext, SlashContext, ComponentContext
import discord.utils
import config
from collections import deque
from youtube_dl import YoutubeDL
from utils.data import input_to_int
from discord_slash.utils.manage_components import create_select, create_select_option, create_actionrow


@dataclass
class Song:
    title: str
    source: str
    thumbnail: str
    web_url: str
    duration: int
    _embed: Union[Embed, None] = None

    @property
    def embed(self):
        if not self._embed:
            embed = Embed(title=self.title, url=self.web_url)
            embed.set_thumbnail(url=self.thumbnail)
            embed.add_field(name="Length", value=self.duration_time)
            self._embed = embed
        return self._embed

    @property
    def duration_time(self):
        duration = {}
        duration["hours"], rem = divmod(self.duration, 3600)
        duration["minutes"], duration["seconds"] = divmod(rem, 60)
        if duration["hours"] > 0:
            return f"{duration['hours']:02}:{duration['minutes']:02}:{duration['seconds']:02}"
        return f"{duration['minutes']:02}:{duration['seconds']:02}"


# example cog
class Music(Cog):
    def __init__(self, bot: Bot):
        self.bot: Bot = bot
        self.channel: VoiceChannel = None
        self.voice_client: VoiceClient = None
        self.is_playing: bool = False
        self.is_paused: bool = False
        self.volume: float = 0.15
        self.is_stopped: bool = False
        self.now_playing: Song = Song(title="Nothing", source="", thumbnail="", web_url="", duration=-1)

        # consder db support so playlist can survive restarts
        self.music_queue: typing.Deque[Song] = deque()

        self.YTDL_OPTIONS = {"format": "bestaudio", "noplaylist": "True", "logger": config.ytdl_logger}
        self.FFMPEG_OPTIONS = {
            "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            "options": "-vn",
        }

    ################
    ## JOIN/LEAVE ##
    ################
    @cog_ext.cog_slash(
        name="join",
        description=f"Ask RoosterBot to join you in a voice channel",
    )
    async def _join(self, ctx: SlashContext) -> typing.Union[bool, None]:
        await self.join(ctx)

    async def join(self, ctx: SlashContext):
        self.update_voice_state(ctx)
        try:
            join_channel = ctx.author.voice.channel
        except AttributeError:
            await ctx.reply("you are not in a voice channel")
            return False
        if self.channel and self.channel.id == join_channel.id:
            await ctx.reply(f"{self.bot.user.name} is already in **{join_channel}**")
            return
        await join_channel.connect()
        self.channel = join_channel
        self.voice_client = ctx.guild.voice_client
        await ctx.reply(f"{self.bot.user.name} has joined **{join_channel}** ")

    @cog_ext.cog_slash(
        name="leave",
        description=f"Ask RoosterBot to leave the voice channel",
    )
    async def _leave(self, ctx: SlashContext):
        if self.check_connected(ctx):
            await ctx.guild.voice_client.disconnect()
            await ctx.reply("Goodbye!")
            self.channel = None
        else:
            await ctx.reply(f"{self.bot.user.name} is not in a voice channel")

    #####################
    ## MANAGE PLAYLIST ##
    #####################

    @cog_ext.cog_slash(
        name="add",
        description=f"Add a song to the playlist",
        options=[
            {
                "name": "song",
                "description": "the song you want to add to the playlist",
                "type": 3,
                "required": True,
            },
        ],
    )
    async def _add(self, ctx: SlashContext, song: str):
        await ctx.defer()
        if song_result := self.search_youtube(song)[0]:
            self.music_queue.append(song_result)
            song_result.embed.set_footer(text=f"Added by {ctx.author.nick}", icon_url=ctx.author.avatar_url)
            song_result.embed.color = discord.Color.green()
            await ctx.send(f":white_check_mark:  **{song_result.title}** successfully added!", embed=song_result.embed)

            return
        await ctx.reply(f":x:  **{song}** could not be found: ")

    @cog_ext.cog_slash(
        name="playlist",
        description=f"List songs in the playlist",
    )
    async def _playlist(self, ctx: SlashContext):
        embed = self.playlist_embed()
        await ctx.reply(embed=embed)

    def playlist_embed(self):
        embed = Embed(title=f"Playlist ({len(self.music_queue)} tracks)", color=discord.Color.purple())
        track_list = []
        for idx, track in enumerate(self.music_queue):
            track_list.append(f"`{idx+1}` [{track.title}]({track.web_url}) {track.duration_time}")
        if track_list:
            embed.description = "\n".join(track_list)
        return embed

    ############
    ##  PLAY  ##
    ############
    @cog_ext.cog_slash(
        name="play",
        description=f"Start playing from the playlist",
    )
    async def _play(self, ctx: SlashContext):
        self.is_stopped = False
        if not self.check_connected(ctx):
            can_join = await self.join(ctx)
            if can_join == False:
                await ctx.reply("Please join a voice channel first")
                return
        if len(self.music_queue) > 0:
            await ctx.reply(f"**Now Playing**", embed=self.music_queue[0].embed)
            self.play_next()
        else:
            await ctx.reply(f"I don't have any songs to play, please add one first")

    def play_next(self):
        if self.is_stopped:
            config.logger.info("playing next stopped")
            return
        if len(self.music_queue) > 0:
            self.is_playing = True

            track = self.music_queue.popleft()
            source = PCMVolumeTransformer(FFmpegPCMAudio(track.source, **self.FFMPEG_OPTIONS), volume=self.volume)
            self.voice_client.play(source, after=lambda x: self.play_next())
            self.now_playing = track
        else:
            self.is_playing = False

    ##########
    ## STOP ##
    ##########
    @cog_ext.cog_slash(
        name="stop",
        description=f"Stop playing from the playlist",
    )
    async def _stop(self, ctx: SlashContext):
        if self.is_playing:
            try:
                self.stop()
            except Exception as e:
                config.logger.error(f"Could not stop playing: {e}")
                await ctx.reply("Unable stop playing")
            await ctx.reply(f"**Stopping** {self.now_playing.title}")
        else:
            await ctx.reply("Nothing is playing")

    def stop(self):
        """Stops playing music"""
        if self.is_playing:
            self.is_stopped = True
            self.voice_client.stop()
            self.is_playing = False

    ############
    ## VOLUME ##
    ############
    @cog_ext.cog_slash(
        name="volume",
        description=f"Change the volume of player, leave blank to get current volume",
        options=[{"type": 3, "name": "volume", "description": "Volume [1-100] (ex: 40%)"}],
    )
    async def _volume(self, ctx: SlashContext, volume: str = None):
        if not volume:
            await ctx.reply(f"Volume is set to {int(self.volume * 100)}%")
        if self.is_playing:
            try:
                self.set_volume(input_to_int(volume))
            except Exception as e:
                config.logger.error(f"Could not change volume: \n{e}")
                await ctx.reply("Volume could not be changed")
                return
            await ctx.reply(f"Volume changed to {volume}")

    def set_volume(self, volume: int):
        """Sets the volume of the plays
        @param volume[int]: desired volume 0-100"""
        clamped_volume = max(min(volume, 100), 0)
        self.volume = clamped_volume / 100
        if self.is_playing:
            self.voice_client.source.volume = self.volume

    def get_volume(self):
        return self.volume * 100

    ############
    ## PAUSE ##
    ############
    @cog_ext.cog_slash(
        name="pause",
        description=f"Pause/Resume the current playing track",
    )
    async def _pause(self, ctx: SlashContext):
        await ctx.reply(f"**{'Pausing' if not self.is_paused else 'Resuming'}:** {self.now_playing.title}")
        try:
            self.pause_resume()
        except Exception as e:
            config.logger.error(f"Was not able to pause/resume: {e}")
            await ctx.reply("Unable to pause/resume")

    def pause_resume(self):
        """Pause/Resume playing music, keeps place on current track"""
        if self.is_playing and not self.is_paused:
            self.voice_client.pause()
            self.is_paused = True
        elif self.is_paused:
            self.voice_client.resume()
            self.is_paused = False

    ##########
    ## Skip ##
    ##########
    @cog_ext.cog_slash(
        name="skip",
        description=f"Skip the current track",
    )
    async def _skip(self, ctx: SlashContext):
        if self.is_playing and len(self.music_queue) > 0:
            await ctx.reply(f"Skipping {self.now_playing.title}")
            self.voice_client.stop()
        elif self.is_playing and len(self.music_queue) == 0:
            await ctx.reply("There are no more tracks in the playlist, stopping instead")
            self.stop()
        else:
            await ctx.reply("Nothing is playing")

    ############
    ## Remove ##
    ############
    @cog_ext.cog_slash(
        name="remove",
        description=f"Skip the current track",
        options=[
            {"name": "track_number", "description": "Number of the track to remove", "type": 4, "required": False}
        ],
    )
    async def _remove(self, ctx: SlashContext, track_number: int = None):
        if track_number and len(self.music_queue) >= track_number:
            track_title = self.music_queue[track_number - 1].title
            del self.music_queue[track_number - 1]
            await ctx.reply(f":white_check_mark: **{track_title}** successfully removed!", embed=self.playlist_embed())
        else:

            options = [
                create_select_option(
                    item.title,
                    value=f"{i}",
                )
                for (i, item) in enumerate(self.music_queue)
            ]

            select = create_select(
                options, placeholder="select a track to remove", min_values=1, max_values=1, custom_id="remove_select"
            )

            await ctx.send(
                "Which track would you like to remove from the playlist?",
                components=[create_actionrow(select)],
                embed=self.playlist_embed(),
            )

    def remove_track(self, track):
        del self.music_queue[track]

    async def handle_remove(self, ctx: ComponentContext):
        config.logger.debug(f"{ctx.custom_id} {ctx.selected_options}")
        selected_track = int(ctx.selected_options[0])
        track_title = self.music_queue[selected_track].title
        self.remove_track(selected_track)
        await ctx.edit_origin(
            content=f":white_check_mark: **{track_title}** successfully removed!",
            embed=self.playlist_embed(),
            components=[],
        )

    @Cog.listener()
    async def on_component(self, ctx: ComponentContext):
        if ctx.custom_id == "remove_select":
            await self.handle_remove(ctx)

    #############
    ## HELPERS ##
    #############

    def search_youtube(self, song: str, multiple=False, max_entries=10) -> Union[list[Song], bool]:
        with YoutubeDL(self.YTDL_OPTIONS) as ytdl:
            try:
                results = ytdl.extract_info(f"ytsearch:{song}", download=False)["entries"]
                info = results[0]
            except Exception:
                return False
        if multiple:
            song_results = []
            for song in results[: min(len(results), max_entries)]:
                song_results.append(
                    Song(
                        source=info["formats"][0]["url"],
                        title=info["title"],
                        thumbnail=info["thumbnails"][1]["url"],
                        web_url=info["webpage_url"],
                        duration=info["duration"],
                    )
                )
            return song_results

        return [
            Song(
                source=info["formats"][0]["url"],
                title=info["title"],
                thumbnail=info["thumbnails"][1]["url"],
                web_url=info["webpage_url"],
                duration=info["duration"],
            )
        ]

    def is_voice_playing(self):
        return self.voice_client and self.voice_client.is_playing()

    def is_voice_paused(self):
        return self.voice_client and self.voice_client.is_paused()

    def check_connected(self, ctx):
        voice_client: VoiceClient = discord.utils.get(ctx.bot.voice_clients, guild=ctx.guild)
        return voice_client and voice_client.is_connected()

    def update_voice_state(self, ctx):
        voice_client: VoiceClient = discord.utils.get(ctx.bot.voice_clients, guild=ctx.guild)
        if voice_client:
            self.voice_client = voice_client
            self.channel = voice_client.channel


def setup(bot: Bot):
    bot.add_cog(Music(bot))
