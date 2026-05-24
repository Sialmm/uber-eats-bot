import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os
from datetime import datetime

# ===================== CONFIGURATION =====================
BOT_TOKEN = os.environ.get("TOKEN", "TON_TOKEN_ICI")
GUILD_ID = 1507793475549265971
VENDEUR_ROLE_NAME = "Vendeur"
CATEGORY_ATTENTE = "Commandes - En attente"
CATEGORY_PRISE = "Commandes - Pris en charges"
LOG_CHANNEL_NAME = "logs-commandes"  # Salon où envoyer le récap (crée-le sur Discord)
IMAGE_URL = "https://i.imgur.com/kugHazj.jpeg"
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
ticket_counter = {"count": 0}
ticket_clients = {}       # {channel_id: client_id}
ticket_data = {}          # {channel_id: {montant, adresse, paiement, created_at}}
vendeur_stats = {}        # {vendeur_id: {"nom": str, "count": int}}
clients_en_cours = set()  # set des client_id ayant déjà un ticket ouvert


def is_vendeur(interaction: discord.Interaction) -> bool:
    vendeur_role = discord.utils.get(interaction.guild.roles, name=VENDEUR_ROLE_NAME)
    if vendeur_role is None:
        return interaction.user.guild_permissions.administrator
    return vendeur_role in interaction.user.roles or interaction.user.guild_permissions.administrator


def overwrites_prise(guild, client, vendeur, vendeur_role):
    ow = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_messages=True),
        client: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
        vendeur: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True),
    }
    if vendeur_role:
        ow[vendeur_role] = discord.PermissionOverwrite(view_channel=False)
    return ow


# ───────────────────────────────────────────────
# MODAL
# ───────────────────────────────────────────────
class CommandeModal(discord.ui.Modal, title="🛒 Commande Uber Eats"):
    montant = discord.ui.TextInput(label="Montant HT (sous-total)", placeholder="Min. 20 HT – Max. 23 HT", min_length=1, max_length=10, required=True)
    adresse = discord.ui.TextInput(label="Adresse complète", placeholder="Numéro, rue, code postal, ville", style=discord.TextStyle.paragraph, min_length=10, max_length=200, required=True)
    moyen_paiement = discord.ui.TextInput(label="Moyen de paiement", placeholder="Revolut / PayPal / Virement", min_length=2, max_length=50, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        user = interaction.user

        # ── Anti-doublon ──
        if user.id in clients_en_cours:
            await interaction.followup.send("❌ Tu as déjà un ticket en cours ! Ferme-le avant d'en ouvrir un nouveau.", ephemeral=True)
            return

        ticket_counter["count"] += 1
        ticket_num = ticket_counter["count"]

        vendeur_role = discord.utils.get(guild.roles, name=VENDEUR_ROLE_NAME)
        category = discord.utils.get(guild.categories, name=CATEGORY_ATTENTE)

        channel_name = f"commande-{ticket_num:04d}"
        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            topic=f"Commande de {user.display_name} | N°{ticket_num:04d}",
        )
        await ticket_channel.edit(sync_permissions=True)
        await ticket_channel.set_permissions(user, view_channel=True, send_messages=True, read_message_history=True, attach_files=True)

        # Stocker les infos
        ticket_clients[ticket_channel.id] = user.id
        clients_en_cours.add(user.id)
        ticket_data[ticket_channel.id] = {
            "montant": self.montant.value,
            "adresse": self.adresse.value,
            "paiement": self.moyen_paiement.value,
            "client": user.display_name,
            "client_id": user.id,
            "ticket_num": ticket_num,
            "created_at": datetime.now().strftime("%d/%m/%Y à %H:%M"),
            "vendeur": None,
        }

        embed = discord.Embed(
            description=(
                "**Un vendeur va vous prendre en charge dans les plus brefs délais. "
                "En attendant, envoyez une capture d'écran de votre panier avec tous "
                "les articles bien visibles afin de gagner du temps.**"
            ),
            color=0x06C167,
        )
        embed.add_field(name="Montant HT (sous-total)", value=f"```{self.montant.value}```", inline=False)
        embed.add_field(name="Adresse complète", value=f"```{self.adresse.value}```", inline=False)
        embed.add_field(name="Moyens de paiement", value=f"```{self.moyen_paiement.value}```", inline=False)
        embed.add_field(name="Status", value="```En attente```", inline=False)
        embed.set_image(url=IMAGE_URL)

        mention = user.mention
        if vendeur_role:
            mention += f" | {vendeur_role.mention}"

        await ticket_channel.send(content=mention, embed=embed, view=TicketInitView(user_id=user.id))
        await interaction.followup.send(f"✅ Ton ticket a été créé : {ticket_channel.mention}", ephemeral=True)


# ───────────────────────────────────────────────
# VIEW 1 — En attente
# ───────────────────────────────────────────────
class TicketInitView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="✅ Prendre la commande", style=discord.ButtonStyle.success, custom_id="prendre_commande")
    async def prendre(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_vendeur(interaction):
            await interaction.response.send_message("❌ Tu dois avoir le rôle **Vendeur**.", ephemeral=True)
            return

        await interaction.response.defer()

        guild = interaction.guild
        channel = interaction.channel
        vendeur = interaction.user
        vendeur_role = discord.utils.get(guild.roles, name=VENDEUR_ROLE_NAME)
        category_prise = discord.utils.get(guild.categories, name=CATEGORY_PRISE)

        client_id = ticket_clients.get(channel.id)
        client = guild.get_member(client_id) if client_id else None

        await channel.edit(
            category=category_prise,
            overwrites=overwrites_prise(guild, client, vendeur, vendeur_role) if client else {},
        )

        # Mettre à jour les stats vendeur
        if vendeur.id not in vendeur_stats:
            vendeur_stats[vendeur.id] = {"nom": vendeur.display_name, "count": 0}
        if channel.id in ticket_data:
            ticket_data[channel.id]["vendeur"] = vendeur.display_name

        old_embed = interaction.message.embeds[0]
        new_embed = discord.Embed(description=old_embed.description, color=0x06C167)
        for field in old_embed.fields:
            if field.name == "Status":
                new_embed.add_field(name="Status", value=f"```Pris en charge (par {vendeur.display_name})```", inline=False)
            else:
                new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
        new_embed.set_image(url=IMAGE_URL)

        await interaction.message.edit(embed=new_embed, view=TicketActiveView(user_id=self.user_id))
        await interaction.followup.send(f"📦 Commande attribuée à {vendeur.mention}.")

    @discord.ui.button(label="🔒 Fermer le ticket", style=discord.ButtonStyle.danger, custom_id="fermer_init")
    async def fermer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_vendeur(interaction):
            await interaction.response.send_message("❌ Tu dois avoir le rôle **Vendeur**.", ephemeral=True)
            return
        embed = discord.Embed(title="🔒 Ticket fermé", description=f"Fermé par {interaction.user.mention}. Suppression dans **1 heure**.", color=0xED4245)
        await interaction.response.send_message(embed=embed)
        client_id = ticket_clients.get(interaction.channel.id)
        clients_en_cours.discard(client_id)
        ticket_clients.pop(interaction.channel.id, None)
        ticket_data.pop(interaction.channel.id, None)
        await asyncio.sleep(3600)
        await interaction.channel.delete()


# ───────────────────────────────────────────────
# VIEW 2 — Pris en charge
# ───────────────────────────────────────────────
class TicketActiveView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="Mettre en attente", style=discord.ButtonStyle.secondary, custom_id="en_attente")
    async def en_attente(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_vendeur(interaction):
            await interaction.response.send_message("❌ Tu dois avoir le rôle **Vendeur**.", ephemeral=True)
            return

        await interaction.response.defer()

        guild = interaction.guild
        channel = interaction.channel
        category_attente = discord.utils.get(guild.categories, name=CATEGORY_ATTENTE)
        client_id = ticket_clients.get(channel.id)
        client = guild.get_member(client_id) if client_id else None

        await channel.edit(category=category_attente)
        await channel.edit(sync_permissions=True)
        if client:
            await channel.set_permissions(client, view_channel=True, send_messages=True, read_message_history=True, attach_files=True)

        old_embed = interaction.message.embeds[0]
        new_embed = discord.Embed(description=old_embed.description, color=0x06C167)
        for field in old_embed.fields:
            if field.name == "Status":
                new_embed.add_field(name="Status", value="```En attente```", inline=False)
            else:
                new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
        new_embed.set_image(url=IMAGE_URL)

        await interaction.message.edit(embed=new_embed, view=TicketInitView(user_id=self.user_id))
        await interaction.followup.send(f"⏸️ Commande remise **en attente** par {interaction.user.mention}.")

    @discord.ui.button(label="Commande traitée", style=discord.ButtonStyle.success, custom_id="traitee")
    async def traitee(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_vendeur(interaction):
            await interaction.response.send_message("❌ Tu dois avoir le rôle **Vendeur**.", ephemeral=True)
            return

        vendeur = interaction.user
        channel = interaction.channel
        guild = interaction.guild
        data = ticket_data.get(channel.id, {})

        # Incrémenter les stats
        if vendeur.id not in vendeur_stats:
            vendeur_stats[vendeur.id] = {"nom": vendeur.display_name, "count": 0}
        vendeur_stats[vendeur.id]["count"] += 1
        vendeur_stats[vendeur.id]["nom"] = vendeur.display_name

        old_embed = interaction.message.embeds[0]
        new_embed = discord.Embed(description=old_embed.description, color=discord.Color.green())
        for field in old_embed.fields:
            if field.name == "Status":
                new_embed.add_field(name="Status", value=f"```Traitée (par {vendeur.display_name})```", inline=False)
            else:
                new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
        new_embed.set_image(url=IMAGE_URL)

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=new_embed, view=self)
        await interaction.followup.send(f"✅ Commande **traitée** par {vendeur.mention} ! Suppression dans **1 heure**.")

        # ── Récap dans le salon logs ──
        log_channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
        if log_channel and data:
            recap = discord.Embed(
                title=f"📋 Récap — Commande N°{data.get('ticket_num', '?'):04d}",
                color=discord.Color.green(),
                timestamp=datetime.now(),
            )
            recap.add_field(name="👤 Client", value=f"`{data.get('client', '?')}`", inline=True)
            recap.add_field(name="🧑‍💼 Vendeur", value=f"`{vendeur.display_name}`", inline=True)
            recap.add_field(name="💰 Montant HT", value=f"`{data.get('montant', '?')}`", inline=True)
            recap.add_field(name="💳 Paiement", value=f"`{data.get('paiement', '?')}`", inline=True)
            recap.add_field(name="📍 Adresse", value=f"```{data.get('adresse', '?')}```", inline=False)
            recap.set_footer(text=f"Commande créée le {data.get('created_at', '?')}")
            await log_channel.send(embed=recap)

        # Nettoyage
        client_id = ticket_clients.pop(channel.id, None)
        clients_en_cours.discard(client_id)
        ticket_data.pop(channel.id, None)

        await asyncio.sleep(3600)
        await channel.delete()


# ───────────────────────────────────────────────
# VIEW — Bouton principal
# ───────────────────────────────────────────────
class CommanderView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🛒 Commander maintenant", style=discord.ButtonStyle.success, custom_id="open_commande")
    async def commander(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CommandeModal())


# ───────────────────────────────────────────────
# COMMANDE SLASH — /panel
# ───────────────────────────────────────────────
@bot.tree.command(name="panel", description="Affiche le panneau de commande Uber Eats")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def panel(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Permission refusée.", ephemeral=True)
        return
    embed = discord.Embed(
        title="🛒 Commander",
        description=(
            "**Commande ton Uber Eats à -50%** simplement et rapidement.\n\n"
            "Une fois le bouton sélectionné, tu devras renseigner **toutes les informations demandées**. "
            "Dès que c'est complété, **un ticket sera créé automatiquement**.\n\n"
            "Ta commande passera ensuite en attente jusqu'à ce qu'un **vendeur** la prenne en charge.\n\n"
            "Tu devras envoyer **une capture d'écran de ton panier avec tous les articles bien visibles**."
        ),
        color=0x06C167,
    )
    embed.set_image(url=IMAGE_URL)
    embed.set_footer(text="⚠️ Ne donne jamais ton mot de passe ni d'informations sensibles.")
    await interaction.response.send_message(embed=embed, view=CommanderView())


# ───────────────────────────────────────────────
# COMMANDE SLASH — /stats
# ───────────────────────────────────────────────
@bot.tree.command(name="stats", description="Affiche les statistiques des vendeurs")
@app_commands.guilds(discord.Object(id=GUILD_ID))
async def stats(interaction: discord.Interaction):
    if not is_vendeur(interaction):
        await interaction.response.send_message("❌ Réservé aux vendeurs.", ephemeral=True)
        return

    if not vendeur_stats:
        await interaction.response.send_message("📊 Aucune statistique disponible pour le moment.", ephemeral=True)
        return

    embed = discord.Embed(title="📊 Statistiques des vendeurs", color=0x5865F2, timestamp=datetime.now())

    # Trier par nombre de commandes
    sorted_stats = sorted(vendeur_stats.items(), key=lambda x: x[1]["count"], reverse=True)
    classement = ""
    medals = ["🥇", "🥈", "🥉"]
    for i, (vid, vdata) in enumerate(sorted_stats):
        medal = medals[i] if i < 3 else f"`#{i+1}`"
        classement += f"{medal} **{vdata['nom']}** — {vdata['count']} commande(s)\n"

    embed.add_field(name="Classement", value=classement or "Aucun", inline=False)
    embed.set_footer(text=f"Total commandes traitées : {sum(v['count'] for v in vendeur_stats.values())}")
    await interaction.response.send_message(embed=embed)


# ───────────────────────────────────────────────
# EVENTS
# ───────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Bot connecté : {bot.user} ({bot.user.id})")
    try:
        guild = discord.Object(id=GUILD_ID)
        synced = await bot.tree.sync(guild=guild)
        print(f"✅ {len(synced)} commande(s) slash synchronisée(s).")
    except Exception as e:
        print(f"❌ Erreur sync : {e}")
    bot.add_view(CommanderView())
    bot.add_view(TicketInitView(user_id=0))
    bot.add_view(TicketActiveView(user_id=0))


bot.run(BOT_TOKEN)
