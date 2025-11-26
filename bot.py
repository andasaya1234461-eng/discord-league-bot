import discord
from discord import app_commands
from discord.ext import commands
import json
import os
from flask import Flask
import threading
import asyncio

# Flask app untuk Northflank + UptimeRobot
app = Flask(__name__)

@app.route('/')
def home():
    return "✅ Discord League Bot is running!"

@app.route('/health')
def health():
    return "🟢 Healthy"

@app.route('/ping')
def ping():
    return "pong"

def run_flask():
    port = int(os.environ.get('PORT', 8080))  # Northflank pakai port 8080
    app.run(host='0.0.0.0', port=port)

# Bot setup
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

# Data storage
class DataManager:
    def __init__(self):
        self.data_file = '/tmp/league_data.json'  # Pakai /tmp untuk persistence
        self.data = self.load_data()
    
    def load_data(self):
        try:
            with open(self.data_file, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
    
    def save_data(self):
        with open(self.data_file, 'w') as f:
            json.dump(self.data, f, indent=4)
    
    def get_guild_data(self, guild_id):
        guild_id = str(guild_id)
        if guild_id not in self.data:
            self.data[guild_id] = {
                'manager_role': None,
                'assistant_manager_role': None,
                'free_agent_role': None,
                'transfer_channel': None,
                'teams': {}
            }
        return self.data[guild_id]
    
    def save_guild_data(self, guild_id, data):
        guild_id = str(guild_id)
        self.data[guild_id] = data
        self.save_data()

data_manager = DataManager()

@bot.event
async def on_ready():
    print(f'✅ {bot.user} has connected to Discord!')
    print(f'✅ Bot is in {len(bot.guilds)} guilds')
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"❌ Error syncing commands: {e}")

# SIGN COMMAND
@bot.tree.command(name="sign", description="Sign pemain ke tim Anda")
@app_commands.describe(user="User yang akan di-sign")
async def sign(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer(ephemeral=True)
    
    guild_data = data_manager.get_guild_data(interaction.guild_id)
    
    # Check permissions
    user_roles = [role.id for role in interaction.user.roles]
    manager_role_id = guild_data.get('manager_role')
    assistant_role_id = guild_data.get('assistant_manager_role')
    
    if manager_role_id not in user_roles and assistant_role_id not in user_roles:
        await interaction.followup.send("❌ Hanya Manager dan Assistant Manager yang bisa menggunakan command ini!", ephemeral=True)
        return
    
    # Cari tim user
    user_team_id = None
    user_team_role = None
    
    for role in interaction.user.roles:
        if str(role.id) in guild_data.get('teams', {}):
            user_team_id = str(role.id)
            user_team_role = role
            break
    
    if not user_team_id:
        await interaction.followup.send("❌ Anda tidak memiliki tim! Pastikan Anda memiliki role tim yang sudah didaftarkan.", ephemeral=True)
        return
    
    team_data = guild_data['teams'][user_team_id]
    
    # Check if team is full
    if len(team_data.get('players', [])) >= 10:
        await interaction.followup.send("❌ Tim Anda sudah penuh! (Maksimal 10 pemain)", ephemeral=True)
        return
    
    # Check if target user is free agent
    free_agent_role_id = guild_data.get('free_agent_role')
    if free_agent_role_id and free_agent_role_id not in [role.id for role in user.roles]:
        await interaction.followup.send("❌ User ini bukan Free Agent!", ephemeral=True)
        return
    
    # Check if target user is already in a team
    for other_team_id, other_team_data in guild_data.get('teams', {}).items():
        if str(user.id) in other_team_data.get('players', []):
            await interaction.followup.send("❌ User ini sudah berada di tim lain!", ephemeral=True)
            return
    
    # KIRIM DM
    embed = discord.Embed(
        title="🎯 Contract Offer",
        description=f"**{user_team_role.name}** has offered you a contract!",
        color=discord.Color.blue()
    )
    embed.add_field(name="Team", value=user_team_role.mention, inline=True)
    embed.add_field(name="Offered by", value=interaction.user.mention, inline=True)
    embed.add_field(name="Roster Spot", value=f"{len(team_data.get('players', [])) + 1}/10", inline=True)
    
    view = discord.ui.View(timeout=3600)
    
    async def accept_callback(button_interaction: discord.Interaction):
        if button_interaction.user.id != user.id:
            await button_interaction.response.send_message("❌ Ini bukan untuk Anda!", ephemeral=True)
            return
        
        # Add player to team
        if 'players' not in team_data:
            team_data['players'] = []
        team_data['players'].append(str(user.id))
        
        # Update roles
        if free_agent_role_id:
            free_agent_role = interaction.guild.get_role(free_agent_role_id)
            if free_agent_role and free_agent_role in user.roles:
                await user.remove_roles(free_agent_role)
        
        if user_team_role:
            await user.add_roles(user_team_role)
        
        data_manager.save_guild_data(interaction.guild_id, guild_data)
        
        # Send to transfer channel
        transfer_channel_id = guild_data.get('transfer_channel')
        if transfer_channel_id:
            transfer_channel = interaction.guild.get_channel(transfer_channel_id)
            if transfer_channel:
                manager_id = team_data.get('manager')
                assistant_id = team_data.get('assistant_manager')
                
                manager_mention = f"<@{manager_id}>" if manager_id else "Belum ada"
                assistant_mention = f"<@{assistant_id}>" if assistant_id else "Belum ada"
                
                transfer_embed = discord.Embed(title="✅ Signed", color=discord.Color.green())
                transfer_embed.add_field(name="Player", value=user.mention, inline=True)
                transfer_embed.add_field(name="Team", value=user_team_role.mention, inline=True)
                transfer_embed.add_field(name="Manager", value=manager_mention, inline=True)
                transfer_embed.add_field(name="Assistant Manager", value=assistant_mention, inline=True)
                transfer_embed.add_field(name="Roster", value=f"{len(team_data['players'])}/10", inline=True)
                
                await transfer_channel.send(embed=transfer_embed)
        
        await button_interaction.response.edit_message(
            content="✅ Anda telah menerima tawaran kontrak!",
            embed=None,
            view=None
        )
    
    async def decline_callback(button_interaction: discord.Interaction):
        if button_interaction.user.id != user.id:
            await button_interaction.response.send_message("❌ Ini bukan untuk Anda!", ephemeral=True)
            return
        
        await button_interaction.response.edit_message(
            content="❌ Anda telah menolak tawaran kontrak.",
            embed=None,
            view=None
        )
    
    accept_button = discord.ui.Button(style=discord.ButtonStyle.success, label="Accept")
    decline_button = discord.ui.Button(style=discord.ButtonStyle.danger, label="Decline")
    
    accept_button.callback = accept_callback
    decline_button.callback = decline_callback
    
    view.add_item(accept_button)
    view.add_item(decline_button)
    
    try:
        await user.send(embed=embed, view=view)
        await interaction.followup.send(f"✅ Offer telah dikirim ke {user.mention}!", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send(f"❌ Tidak bisa mengirim DM ke {user.mention}. Pastikan DM mereka terbuka!", ephemeral=True)

# SETUP COMMAND
@bot.tree.command(name="setup", description="Setup roles dan channel untuk liga (Owner only)")
@app_commands.describe(
    manager_role="Role untuk Manager",
    assistant_manager_role="Role untuk Assistant Manager", 
    free_agent_role="Role untuk Free Agent",
    transfer_channel="Channel untuk transfer"
)
async def setup(interaction: discord.Interaction, manager_role: discord.Role, assistant_manager_role: discord.Role, 
                free_agent_role: discord.Role, transfer_channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Hanya owner server yang bisa menggunakan command ini!", ephemeral=True)
        return
    
    guild_data = data_manager.get_guild_data(interaction.guild_id)
    guild_data['manager_role'] = manager_role.id
    guild_data['assistant_manager_role'] = assistant_manager_role.id
    guild_data['free_agent_role'] = free_agent_role.id
    guild_data['transfer_channel'] = transfer_channel.id
    
    data_manager.save_guild_data(interaction.guild_id, guild_data)
    
    embed = discord.Embed(title="✅ Setup Berhasil", color=discord.Color.green())
    embed.add_field(name="Manager Role", value=manager_role.mention, inline=True)
    embed.add_field(name="Assistant Manager", value=assistant_manager_role.mention, inline=True)
    embed.add_field(name="Free Agent Role", value=free_agent_role.mention, inline=True)
    embed.add_field(name="Transfer Channel", value=transfer_channel.mention, inline=True)
    
    await interaction.response.send_message(embed=embed)

# ADD TEAM COMMAND
@bot.tree.command(name="addteam", description="Tambahkan tim baru (Owner only)")
@app_commands.describe(
    team_role="Role untuk tim",
    emoji="Emoji untuk tim"
)
async def addteam(interaction: discord.Interaction, team_role: discord.Role, emoji: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Hanya owner server yang bisa menggunakan command ini!", ephemeral=True)
        return
    
    guild_data = data_manager.get_guild_data(interaction.guild_id)
    
    guild_data['teams'][str(team_role.id)] = {
        'emoji': emoji,
        'manager': str(interaction.user.id),
        'assistant_manager': None,
        'players': []
    }
    
    data_manager.save_guild_data(interaction.guild_id, guild_data)
    
    await interaction.response.send_message(f"✅ Tim {team_role.mention} berhasil ditambahkan! Anda otomatis jadi Manager.")

# ROSTERS COMMAND
@bot.tree.command(name="rosters", description="Lihat roster tim")
@app_commands.describe(team_role="Role tim yang ingin dilihat")
async def rosters(interaction: discord.Interaction, team_role: discord.Role = None):
    guild_data = data_manager.get_guild_data(interaction.guild_id)
    
    if team_role:
        team_data = guild_data.get('teams', {}).get(str(team_role.id))
        if not team_data:
            await interaction.response.send_message("❌ Tim tidak ditemukan!", ephemeral=True)
            return
        
        embed = discord.Embed(title=f"📊 Roster {team_role.name}", color=discord.Color.blue())
        
        manager_id = team_data.get('manager')
        assistant_id = team_data.get('assistant_manager')
        players = team_data.get('players', [])
        
        manager_mention = f"<@{manager_id}>" if manager_id else "Belum ada"
        assistant_mention = f"<@{assistant_id}>" if assistant_id else "Belum ada"
        player_mentions = "\n".join([f"<@{player_id}>" for player_id in players]) if players else "Tidak ada pemain"
        
        embed.add_field(name="Manager", value=manager_mention, inline=True)
        embed.add_field(name="Assistant Manager", value=assistant_mention, inline=True)
        embed.add_field(name=f"Players ({len(players)}/10)", value=player_mentions, inline=False)
        
        await interaction.response.send_message(embed=embed)
    else:
        embed = discord.Embed(title="🏆 All Teams", color=discord.Color.blue())
        
        teams = guild_data.get('teams', {})
        if not teams:
            embed.description = "Belum ada tim yang terdaftar."
        else:
            for team_role_id, team_data in teams.items():
                team_role_obj = interaction.guild.get_role(int(team_role_id))
                if team_role_obj:
                    player_count = len(team_data.get('players', []))
                    manager_id = team_data.get('manager')
                    manager_mention = f"<@{manager_id}>" if manager_id else "Belum ada"
                    
                    embed.add_field(
                        name=f"{team_data.get('emoji', '⚪')} {team_role_obj.name}",
                        value=f"Pemain: {player_count}/10\nManager: {manager_mention}",
                        inline=True
                    )
        
        await interaction.response.send_message(embed=embed)

# RELEASE COMMAND
@bot.tree.command(name="release", description="Release pemain dari tim Anda")
@app_commands.describe(user="User yang akan di-release")
async def release(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer(ephemeral=True)
    
    guild_data = data_manager.get_guild_data(interaction.guild_id)
    
    # Check permissions
    user_roles = [role.id for role in interaction.user.roles]
    manager_role_id = guild_data.get('manager_role')
    assistant_role_id = guild_data.get('assistant_manager_role')
    
    if manager_role_id not in user_roles and assistant_role_id not in user_roles:
        await interaction.followup.send("❌ Hanya Manager dan Assistant Manager yang bisa menggunakan command ini!", ephemeral=True)
        return
    
    # Cari tim user
    user_team_id = None
    user_team_role = None
    
    for role in interaction.user.roles:
        if str(role.id) in guild_data.get('teams', {}):
            user_team_id = str(role.id)
            user_team_role = role
            break
    
    if not user_team_id:
        await interaction.followup.send("❌ Anda tidak memiliki tim!", ephemeral=True)
        return
    
    team_data = guild_data['teams'][user_team_id]
    
    # Check if target user is in the team
    if str(user.id) not in team_data.get('players', []):
        await interaction.followup.send("❌ User ini tidak berada di tim Anda!", ephemeral=True)
        return
    
    # Send DM confirmation
    embed = discord.Embed(
        title="⚠️ Release Notification",
        description=f"**{user_team_role.name}** wants to release you from the team.",
        color=discord.Color.orange()
    )
    embed.add_field(name="Team", value=user_team_role.mention, inline=True)
    embed.add_field(name="Released by", value=interaction.user.mention, inline=True)
    
    view = discord.ui.View(timeout=3600)
    
    async def accept_release_callback(button_interaction: discord.Interaction):
        if button_interaction.user.id != user.id:
            await button_interaction.response.send_message("❌ Ini bukan untuk Anda!", ephemeral=True)
            return
        
        # Remove player from team
        team_data['players'] = [p for p in team_data['players'] if p != str(user.id)]
        
        # Update roles
        free_agent_role_id = guild_data.get('free_agent_role')
        if free_agent_role_id:
            free_agent_role = interaction.guild.get_role(free_agent_role_id)
            if free_agent_role:
                await user.add_roles(free_agent_role)
        
        if user_team_role and user_team_role in user.roles:
            await user.remove_roles(user_team_role)
        
        data_manager.save_guild_data(interaction.guild_id, guild_data)
        
        # Send to transfer channel
        transfer_channel_id = guild_data.get('transfer_channel')
        if transfer_channel_id:
            transfer_channel = interaction.guild.get_channel(transfer_channel_id)
            if transfer_channel:
                manager_id = team_data.get('manager')
                assistant_id = team_data.get('assistant_manager')
                
                manager_mention = f"<@{manager_id}>" if manager_id else "Belum ada"
                assistant_mention = f"<@{assistant_id}>" if assistant_id else "Belum ada"
                
                transfer_embed = discord.Embed(title="📢 Released", color=discord.Color.orange())
                transfer_embed.add_field(name="Player", value=user.mention, inline=True)
                transfer_embed.add_field(name="Team", value=user_team_role.mention, inline=True)
                transfer_embed.add_field(name="Manager", value=manager_mention, inline=True)
                transfer_embed.add_field(name="Assistant Manager", value=assistant_mention, inline=True)
                transfer_embed.add_field(name="Roster", value=f"{len(team_data['players'])}/10", inline=True)
                
                await transfer_channel.send(embed=transfer_embed)
        
        await button_interaction.response.edit_message(
            content="✅ Anda telah menerima release dari tim!",
            embed=None,
            view=None
        )
    
    async def decline_release_callback(button_interaction: discord.Interaction):
        if button_interaction.user.id != user.id:
            await button_interaction.response.send_message("❌ Ini bukan untuk Anda!", ephemeral=True)
            return
        
        await button_interaction.response.edit_message(
            content="❌ Anda telah menolak release dari tim.",
            embed=None,
            view=None
        )
    
    accept_button = discord.ui.Button(style=discord.ButtonStyle.success, label="Accept")
    decline_button = discord.ui.Button(style=discord.ButtonStyle.danger, label="Decline")
    
    accept_button.callback = accept_release_callback
    decline_button.callback = decline_release_callback
    
    view.add_item(accept_button)
    view.add_item(decline_button)
    
    try:
        await user.send(embed=embed, view=view)
        await interaction.followup.send(f"✅ Release confirmation telah dikirim ke {user.mention}!", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send(f"❌ Tidak bisa mengirim DM ke {user.mention}. Pastikan DM mereka terbuka!", ephemeral=True)

# DEBUG COMMAND
@bot.tree.command(name="debug", description="Cek status bot")
async def debug(interaction: discord.Interaction):
    guild_data = data_manager.get_guild_data(interaction.guild_id)
    
    user_roles = [role.id for role in interaction.user.roles]
    manager_role_id = guild_data.get('manager_role')
    assistant_role_id = guild_data.get('assistant_manager_role')
    
    user_team_id = None
    for role in interaction.user.roles:
        if str(role.id) in guild_data.get('teams', {}):
            user_team_id = str(role.id)
            break
    
    debug_info = f"""
**🤖 BOT DEBUG INFO**

**User**: {interaction.user.display_name}
**Has Manager Role**: {'✅ YES' if manager_role_id in user_roles else '❌ NO'}
**Has Assistant Role**: {'✅ YES' if assistant_role_id in user_roles else '❌ NO'}
**Your Team**: {f'<@&{user_team_id}>' if user_team_id else '❌ NO TEAM'}
**Total Teams**: {len(guild_data.get('teams', {}))}
**Bot Ping**: {round(bot.latency * 1000)}ms
"""
    
    await interaction.response.send_message(debug_info, ephemeral=True)

# REMOVE TEAM COMMAND
@bot.tree.command(name="removeteam", description="Hapus tim (Owner only)")
@app_commands.describe(team_role="Role tim yang akan dihapus")
async def removeteam(interaction: discord.Interaction, team_role: discord.Role):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Hanya owner server yang bisa menggunakan command ini!", ephemeral=True)
        return
    
    guild_data = data_manager.get_guild_data(interaction.guild_id)
    
    if str(team_role.id) not in guild_data.get('teams', {}):
        await interaction.response.send_message("❌ Tim tidak ditemukan!", ephemeral=True)
        return
    
    del guild_data['teams'][str(team_role.id)]
    data_manager.save_guild_data(interaction.guild_id, guild_data)
    
    await interaction.response.send_message(f"✅ Tim {team_role.mention} berhasil dihapus!")

# Run the bot
async def main():
    # Start Flask server in background
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print("✅ Flask server started on port 8080")
    
    # Run Discord bot
    token = os.environ.get('DISCORD_TOKEN')
    if not token:
        print("❌ DISCORD_TOKEN not found in environment variables!")
        return
    
    await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())
