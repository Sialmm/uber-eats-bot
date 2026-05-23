import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os

# ===================== CONFIGURATION =====================
BOT_TOKEN = os.environ.get("TOKEN", "TON_TOKEN_ICI")
GUILD_ID = 1507793475549265971
VENDEUR_ROLE_NAME = "Vendeur"
CATEGORY_NAME = "Commandes - En attente"
LOG_CHANNEL_ID = None
IMAGE_URL = "https://i.imgur.com/kugHazj.jpeg"  # Remplace par ton image
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
ticket_counter = {"count": 0}


def is_vendeur(interaction: discord.Interaction) -> bool:
    vendeur_role = discord.utils.get(interaction.guild.roles, name=VENDEUR_ROLE_NAME)
    if vendeur_role is None:
        return interaction.user.guild_permissions.administrator
    return vendeur_role in interaction.user.roles or interaction.user.guild_permissions.administrator


# ───────────────────────────────────────────────
# MODAL
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
        placeholder="Revolut / PayPal / Virement",
        min_length=2,
        max_length=50,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        user = interaction.user

        ticket_counter["count"] += 1
        ticket_num = ticket_counter["count"]

        vendeur_role = discord.utils.get(guild.roles, name=VENDEUR_ROLE_NAME)
        category = discord.utils.get(guild.categories, name=CATEGORY_NAME)

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
        if vendeur_role:
            overwrites[vendeur_role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            )

        channel_name = f"commande-{ticket_num:04d}"
        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            overwrites=overwrites,
            category=category,
            topic=f"Commande de {user.display_name} | N°{ticket_num:04d}",
        )

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

        view = TicketInitView(user_id=user.id)
        await ticket_channel.send(content=mention, embed=embed, view=view)

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
# VIEW 1 — Boutons initiaux : Prendre / Fermer
# ───────────────────────────────────────────────
class TicketInitView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="✅ Prendre la commande", style=discord.ButtonStyle.success, custom_id="prendre_commande")
    async def prendre(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_vendeur(interaction):
            await interaction.response.send_message(
                "❌ Tu dois avoir le rôle **Vendeur** pour effectuer cette action.", ephemeral=True
            )
            return

        vendeur_nom = interaction.user.display_name

        old_embed = interaction.message.embeds[0]
        new_embed = discord.Embed(description=old_embed.description, color=0x06C167)
        for field in old_embed.fields:
            if field.name == "Status":
                new_embed.add_field(
                    name="Status",
                    value=f"```Pris en charge (par {vendeur_nom})```",
                    inline=False,
                )
            else:
                new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
        new_embed.set_image(url=IMAGE_URL)

        new_view = TicketActiveView(user_id=self.user_id)
        await interaction.response.edit_message(embed=new_embed, view=new_view)
        await interaction.followup.send(
            f"📦 Commande attribuée à {interaction.user.mention}."
        )

    @discord.ui.button(label="🔒 Fermer le ticket", style=discord.ButtonStyle.danger, custom_id="fermer_init")
    async def fermer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_vendeur(interaction):
            await interaction.response.send_message(
                "❌ Tu dois avoir le rôle **Vendeur** pour effectuer cette action.", ephemeral=True
            )
            return
        embed = discord.Embed(
            title="🔒 Ticket fermé",
            description=f"Fermé par {interaction.user.mention}. Suppression dans **1 heure**.",
            color=0xED4245,
        )
        await interaction.response.send_message(embed=embed)
        await asyncio.sleep(3600)
        await interaction.channel.delete()


# ───────────────────────────────────────────────
# VIEW 2 — Boutons après prise en charge
# ───────────────────────────────────────────────
class TicketActiveView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="Mettre en attente", style=discord.ButtonStyle.secondary, custom_id="en_attente")
    async def en_attente(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_vendeur(interaction):
            await interaction.response.send_message(
                "❌ Tu dois avoir le rôle **Vendeur** pour effectuer cette action.", ephemeral=True
            )
            return

        old_embed = interaction.message.embeds[0]
        new_embed = discord.Embed(description=old_embed.description, color=0x06C167)
        for field in old_embed.fields:
            if field.name == "Status":
                new_embed.add_field(name="Status", value="```En attente```", inline=False)
            else:
                new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
        new_embed.set_image(url=IMAGE_URL)

        new_view = TicketInitView(user_id=self.user_id)
        await interaction.response.edit_message(embed=new_embed, view=new_view)
        await interaction.followup.send(f"⏸️ Commande remise **en attente** par {interaction.user.mention}.")

    @discord.ui.button(label="Commande traitée", style=discord.ButtonStyle.success, custom_id="traitee")
    async def traitee(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_vendeur(interaction):
            await interaction.response.send_message(
                "❌ Tu dois avoir le rôle **Vendeur** pour effectuer cette action.", ephemeral=True
            )
            return

        old_embed = interaction.message.embeds[0]
        new_embed = discord.Embed(description=old_embed.description, color=discord.Color.green())
        for field in old_embed.fields:
            if field.name == "Status":
                new_embed.add_field(
                    name="Status",
                    value=f"```Traitée (par {interaction.user.display_name})```",
                    inline=False,
                )
            else:
                new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
        new_embed.set_image(url=IMAGE_URL)

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(embed=new_embed, view=self)
        await interaction.followup.send(
            f"✅ Commande **traitée** par {interaction.user.mention} ! Suppression dans **1 heure**."
        )
        await asyncio.sleep(3600)
        await interaction.channel.delete()


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
    embed.set_image(url=IMAGE_URL)
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
    bot.add_view(TicketInitView(user_id=0))
    bot.add_view(TicketActiveView(user_id=0))


bot.run(BOT_TOKEN)
