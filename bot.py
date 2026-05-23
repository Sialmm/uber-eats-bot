import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os

# ===================== CONFIGURATION =====================
BOT_TOKEN = os.environ.get("TOKEN", "TON_TOKEN_ICI")
GUILD_ID = 1507793475549265971       # Remplace par l'ID de ton serveur
CATEGORY_ID = None         # ID de la catégorie pour les tickets (optionnel)
STAFF_ROLE_ID = None       # ID du rôle staff qui peut voir les tickets (optionnel)
LOG_CHANNEL_ID = None      # ID du salon pour les logs (optionnel)
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

ticket_counter = {"count": 0}


# ───────────────────────────────────────────────
# MODAL — Formulaire de commande
# ───────────────────────────────────────────────
class CommandeModal(discord.ui.Modal, title="🛒 Commande Uber Eats"):
    montant = discord.ui.TextInput(
        label="Montant HT (sous-total)",
        placeholder="Min. 20 HT – Max. 23 HT",
        min_length=1,
        max_length=10,
        required=True,
    )
    adresse = discord.ui.TextInput(
        label="Adresse complète",
        placeholder="Numéro, rue, code postal, ville",
        style=discord.TextStyle.paragraph,
        min_length=10,
        max_length=200,
        required=True,
    )
    moyen_paiement = discord.ui.TextInput(
        label="Moyen de paiement",
        placeholder="PayPal / Virement / Crypto / Lydia / Autre",
        min_length=2,
        max_length=50,
        required=True,
    )
    planning = discord.ui.TextInput(
        label="Type de commande",
        placeholder="Maintenant ou Planification (précise la date/heure)",
        min_length=3,
        max_length=100,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        user = interaction.user

        ticket_counter["count"] += 1
        ticket_num = ticket_counter["count"]

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
            ),
        }

        if STAFF_ROLE_ID:
            staff_role = guild.get_role(STAFF_ROLE_ID)
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                )

        category = None
        if CATEGORY_ID:
            category = guild.get_channel(CATEGORY_ID)

        channel_name = f"ticket-{ticket_num:04d}"
        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            category=category,
            topic=f"Commande Uber Eats de {user.display_name} | Ticket #{ticket_num:04d}",
        )

        embed = discord.Embed(
            title=f"🛒 Commande Uber Eats — Ticket #{ticket_num:04d}",
            description=(
                f"Bienvenue {user.mention} ! Ta commande a bien été enregistrée.\n"
                f"Un vendeur va prendre en charge ta commande dès que possible.\n\n"
                f"> 📸 **N'oublie pas d'envoyer une capture d'écran de ton panier** "
                f"avec tous les articles bien visibles !"
            ),
            color=0x06C167,
        )
        embed.add_field(name="👤 Client", value=f"{user.mention}\n`{user.id}`", inline=True)
        embed.add_field(name="🔢 Ticket", value=f"`#{ticket_num:04d}`", inline=True)
        embed.add_field(name="⏰ Type de commande", value=f"`{self.planning.value}`", inline=True)
        embed.add_field(name="💰 Montant HT", value=f"`{self.montant.value} HT`", inline=True)
        embed.add_field(name="💳 Moyen de paiement", value=f"`{self.moyen_paiement.value}`", inline=True)
        embed.add_field(name="📍 Adresse de livraison", value=f"```{self.adresse.value}```", inline=False)
        embed.set_footer(text="Uber Eats à -50% • La Dalle")

        view = TicketManageView(user_id=user.id)
        await ticket_channel.send(
            content=f"{user.mention}" + (f" | <@&{STAFF_ROLE_ID}>" if STAFF_ROLE_ID else ""),
            embed=embed,
            view=view,
        )

        if LOG_CHANNEL_ID:
            log_channel = guild.get_channel(LOG_CHANNEL_ID)
            if log_channel:
                log_embed = discord.Embed(
                    title="📋 Nouveau ticket créé",
                    description=f"**Ticket :** {ticket_channel.mention}\n**Client :** {user.mention}",
                    color=0x5865F2,
                )
                await log_channel.send(embed=log_embed)

        await interaction.followup.send(
            f"✅ Ton ticket a été créé : {ticket_channel.mention}", ephemeral=True
        )


# ───────────────────────────────────────────────
# VIEW — Boutons de gestion dans le ticket
# ───────────────────────────────────────────────
class TicketManageView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="✅ Prendre en charge", style=discord.ButtonStyle.success, custom_id="take_ticket")
    async def take_charge(self, interaction: discord.Interaction, button: discord.ui.Button):
        button.disabled = True
        button.label = f"✅ Pris en charge par {interaction.user.display_name}"
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            f"📦 **{interaction.user.mention}** prend en charge cette commande !"
        )

    @discord.ui.button(label="🔒 Fermer le ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🔒 Ticket fermé",
            description=f"Fermé par {interaction.user.mention}. Suppression dans **5 secondes**.",
            color=0xED4245,
        )
        await interaction.response.send_message(embed=embed)
        await asyncio.sleep(5)
        await interaction.channel.delete(reason=f"Ticket fermé par {interaction.user}")


# ───────────────────────────────────────────────
# VIEW — Bouton principal "Commander"
# ───────────────────────────────────────────────
class CommanderView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🛒 Commander maintenant",
        style=discord.ButtonStyle.success,
        custom_id="open_commande",
    )
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
    embed.set_image(url="https://i.imgur.com/kugHazj.jpeg")
    embed.set_footer(text="⚠️ Ne donne jamais ton mot de passe ni d'informations sensibles.")

    await interaction.response.send_message(embed=embed, view=CommanderView())


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


bot.run(BOT_TOKEN)
