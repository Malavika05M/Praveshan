import discord
from discord.ext import commands
import aiohttp
import asyncio
import os
from dotenv import load_dotenv
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

class MusicAPI:
    def __init__(self):
        self.base_url = "https://musicbrainz.org/ws/2/"
        self.lyrics_url = "https://api.lyrics.ovh/v1/"
        self.search_url = "https://api.deezer.com/search"
        self.trending_url = "https://api.deezer.com/editorial/0/charts"
        self.lastfm_url = "http://ws.audioscrobbler.com/2.0/"
        self.session = None
        self.timeout = aiohttp.ClientTimeout(total=10)

    async def create_session(self):
        if not self.session or self.session.closed:
            connector = aiohttp.TCPConnector(force_close=True, enable_cleanup_closed=True)
            self.session = aiohttp.ClientSession(connector=connector, timeout=self.timeout)

    async def close_session(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def fetch_json(self, url, params=None):
        await self.create_session()
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"API request failed: {url} - Status: {response.status}")
                    return None
        except asyncio.TimeoutError:
            logger.error(f"Timeout while accessing: {url}")
            return None
        except Exception as e:
            logger.error(f"Error in fetch_json: {str(e)}")
            return None

    async def get_lyrics(self, artist, title):
        url = f"{self.lyrics_url}{artist}/{title}"
        logger.info(f"Fetching lyrics from: {url}")
        
        data = await self.fetch_json(url)
        if data and 'lyrics' in data:
            return data['lyrics']
        elif data and 'error' in data:
            return f"Error: {data['error']}"
        return None

    async def search_track(self, artist, title):
        await self.create_session()
        
        params = {
            'query': f'artist:"{artist}" AND recording:"{title}"',
            'fmt': 'json',
            'limit': 1
        }
        
        try:
            async with self.session.get(
                f"{self.base_url}recording/",
                params=params
            ) as response:
                
                if response.status == 200:
                    data = await response.json()
                    if data.get('recordings'):
                        recording = data['recordings'][0]
                        return await self._format_track(recording)
                    
        except Exception as e:
            logger.error(f"MusicBrainz search error: {e}")
        
        return None

    async def _format_track(self, recording):
        album = "Unknown Album"
        release_date = ""
        if 'releases' in recording and recording['releases']:
            release = recording['releases'][0]
            album = release.get('title', album)
            if 'date' in release:
                release_date = f" ({release['date']})"
        
        artist = recording.get('artist-credit', [{}])[0].get('name', 'Unknown Artist')
        
        return {
            'title': recording.get('title', 'Unknown Track'),
            'artist': artist,
            'album': f"{album}{release_date}",
            'duration': int(recording.get('length', 0)) // 1000, 
            'url': f"https://musicbrainz.org/recording/{recording['id']}",
            'tags': [tag['name'] for tag in recording.get('tags', [])[:3]]
        }
    
    async def get_trending(self):
        await self.create_session()
        try:
            async with self.session.get(self.trending_url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('tracks', {}).get('data', [])[:10] 
        except Exception as e:
            print(f"Trending error: {e}")
        return []

    async def get_recommendations(self, genre):
        await self.create_session()
        try:
            params = {
                'method': 'tag.gettoptracks',
                'tag': genre,
                'api_key': os.getenv('LASTFM_API_KEY'),
                'format': 'json',
                'limit': 5
            }
            async with self.session.get(self.lastfm_url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return [track['name'] for track in data.get('tracks', {}).get('track', [])]
        except Exception as e:
            print(f"Recommendations error: {e}")
        return []
    
    async def get_mood_songs(self, mood):
        await self.create_session()
        try:
            params = {
                'method': 'tag.gettoptracks',
                'tag': mood,
                'api_key': os.getenv('LASTFM_API_KEY'),
                'format': 'json',
                'limit': 5
            }
            async with self.session.get(self.lastfm_url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return [
                        f"{track['name']} - {track['artist']['name']}" 
                        for track in data.get('tracks', {}).get('track', [])
                    ]
        except Exception as e:
            print(f"Mood songs error: {e}")
        return []

music_api = MusicAPI()

playlists = {}

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    await bot.change_presence(activity=discord.Game(name="/help for commands"))

@bot.command(name='lyrics')
async def lyrics_command(ctx, *, query):
    await ctx.send(f"Searching lyrics for: **{query}**...")
    
    separators = [' by ', ' - ', ' | ']
    artist, title = None, None
    
    for sep in separators:
        if sep in query:
            parts = query.split(sep, 1)
            title = parts[0].strip()
            artist = parts[1].strip()
            break
    
    if not artist:
        track_info = await music_api.search_track(query)
        if track_info:
            artist = track_info['artist']
            title = track_info['title']
        else:
            await ctx.send("❌ Please specify both song and artist (e.g., `/lyrics Hello - Adele`)")
            return
    
    artist = artist.split(' ft.')[0].split(' feat.')[0].strip()
    title = title.split(' (')[0].strip()
    
    logger.info(f"Processed request - Artist: {artist}, Title: {title}")
    
    lyrics = await music_api.get_lyrics(artist, title)
    if not lyrics:
        await ctx.send(f"❌ Couldn't find lyrics for {title} by {artist}")
        return
    
    chunks = [lyrics[i:i+1900] for i in range(0, min(len(lyrics), 5700), 1900)] 
    for chunk in chunks:
        await ctx.send(f"```\n{chunk}\n```")
    if len(lyrics) > 5700:
        await ctx.send("Lyrics truncated due to length...")

@bot.command(name='track')
async def track_info(ctx, *, query):
    parts = query.split(' - ', 1) if ' - ' in query else query.split(' by ', 1)
    title = parts[0].strip()
    artist = parts[1].strip() if len(parts) > 1 else None
    
    if not artist:
        await ctx.send("❌ Please specify both song and artist (e.g. `/track Hello - Adele`)")
        return
    
    await ctx.send(f"Searching for {title} by {artist}...")
    
    track_info = await music_api.search_track(artist, title)
    if not track_info:
        await ctx.send("❌ Couldn't find track information")
        return
    
    embed = discord.Embed(
        title=f"🎵 {track_info['title']}",
        description=f"by {track_info['artist']}",
        color=discord.Color.blue(),
        url=track_info['url']
    )
    
    embed.add_field(name="Album", value=track_info['album'], inline=True)
    
    if track_info['duration'] > 0:
        mins, secs = divmod(track_info['duration'], 60)
        embed.add_field(name="Duration", value=f"{mins}:{secs:02d}", inline=True)
    
    if track_info['tags']:
        embed.add_field(name="Tags", value=", ".join(track_info['tags']), inline=False)
    
    
    await ctx.send(embed=embed)

@bot.command(name='trending')
async def trending_command(ctx):
    await ctx.send("Fetching trending tracks...")
    
    trending = await music_api.get_trending()
    if not trending:
        await ctx.send("❌ Couldn't fetch trending tracks at the moment.")
        return
    
    embed = discord.Embed(
        title="Currently Trending",
        color=discord.Color.gold(),
        timestamp=datetime.utcnow()
    )
    
    for i, track in enumerate(trending[:10], 1): 
        artist = track['artist']['name']
        title = track['title']
        embed.add_field(
            name=f"{i}. {title}",
            value=f"by {artist}",
            inline=False
        )
    
    embed.set_footer(text="Use /lyrics to get lyrics for any of these songs")
    await ctx.send(embed=embed)

@bot.command(name='recommend')
async def recommend_command(ctx, *, genre):
    await ctx.send(f"Getting {genre} recommendations...")
    
    recommendations = await music_api.get_recommendations(genre.lower())
    if not recommendations:
        await ctx.send(f"❌ No recommendations found for {genre}. Try pop, rock, hiphop, etc.")
        return
    
    embed = discord.Embed(
        title=f"🎵 {genre.title()} Recommendations",
        color=discord.Color.green()
    )
    
    for i, track in enumerate(recommendations, 1):
        embed.add_field(name=f"{i}.", value=track, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='mood')
async def mood_command(ctx, *, mood):
    await ctx.send(f"Finding {mood} songs...")
    
    mood_songs = await music_api.get_mood_songs(mood.lower())
    if not mood_songs:
        common_moods = ["happy", "sad", "chill", "energetic", "romantic"]
        await ctx.send(f"❌ No songs found for {mood}. Try: {', '.join(common_moods)}")
        return
    
    embed = discord.Embed(
        title=f"🎧 {mood.title()} Mood Songs",
        color=discord.Color.purple()
    )
    
    for i, song in enumerate(mood_songs, 1):
        embed.add_field(name=f"{i}.", value=song, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='playlist')
async def playlist_command(ctx, action=None, *, song=None):
    user_id = str(ctx.author.id)
    
    if user_id not in playlists:
        playlists[user_id] = []
    
    if action == 'add' and song:
        playlists[user_id].append(song)
        await ctx.send(f"✅ Added '{song}' to your playlist!")
        
    elif action == 'remove' and song:
        if song in playlists[user_id]:
            playlists[user_id].remove(song)
            await ctx.send(f"✅ Removed '{song}' from your playlist!")
        else:
            await ctx.send(f"❌ '{song}' not found in your playlist!")
            
    elif action == 'clear':
        playlists[user_id] = []
        await ctx.send("Your playlist has been cleared!")
        
    elif action == 'view' or action is None:
        if playlists[user_id]:
            embed = discord.Embed(
                title=f"🎶 {ctx.author.name}'s Playlist",
                color=discord.Color.blurple()
            )
            for i, item in enumerate(playlists[user_id], 1):
                embed.add_field(name=f"{i}.", value=item, inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send("Your playlist is empty! Use `/playlist add <song>` to add songs.")
            
    else:
        await ctx.send(
            "Usage: `/playlist [add/remove/view/clear] [song]`\n"
            "Examples:\n"
            "`/playlist add AntiHero`\n"
            "`/playlist view`\n"
            "`/playlist remove AntiHero`\n"
            "`/playlist clear`"
        )

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Command not found! Use `/help` to see available commands.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Missing required argument! Check `/help` for command usage.")
    else:
        await ctx.send(f"❌ An error occurred: {str(error)}")


@bot.event
async def on_disconnect():
    await music_api.close_session()


if __name__ == "__main__":
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    if not TOKEN:
        logger.error("❌ Error: DISCORD_BOT_TOKEN not found in .env file!")
    else:
        bot.run(TOKEN)