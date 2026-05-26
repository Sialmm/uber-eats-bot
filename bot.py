import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os
import io
from datetime import datetime
# ===================== CONFIGURATION =====================
BOT_TOKEN = os.environ.get("TOKEN", "TON_TOKEN_ICI")
GUILD_ID = 1507793475549265971
VENDEUR_ROLE_NAME = "「🧑‍🍳」Vendeur"
CATEGORY_ATTENTE = "Commandes - En attente"
CATEGORY_PRISE = "Commandes - Pris en charges"
CATEGORY_TRAITEE = "Commandes - Traités"
LOG_CHANNEL_NAME = "logs-commandes"
CLASSEMENT_CHANNEL_ID = 1507798083466166272  # Salon classement-vendeurs
IMAGE_URL = "https://i.imgur.com/kugHazj.jpeg"
# =========================================================
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
ticket_counter = {"count": 0}
ticket_clients = {}
ticket_data = {}
vendeur_stats = {}
clients_en_cours = set()
classement_message_id = None  # ID du message classement en direct

def is_vendeur(interaction: discord.Interaction) -> bool:
    vendeur_role = discord.utils.get(interaction.guild.roles, name=VENDEUR_ROLE_NAME)
    if vendeur_role is None:
        return interaction.user.guild_permissions.administrator
    return vendeur_role in interaction.user.roles or interaction.user.guild_permissions.administrator

def overwrites_prise(guild, client, vendeur, vendeur_role):
    ow = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_messages=True),
        vendeur: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True),
    }
    if client:
        ow[client] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
    if vendeur_role:
        ow[vendeur_role] = discord.PermissionOverwrite(view_channel=False)
    return ow

def overwrites_traitee(guild, client, vendeur, vendeur_role):
    return overwrites_prise(guild, client, vendeur, vendeur_role)

async def mettre_a_jour_classement(guild):
    global classement_message_id
    channel = guild.get_channel(CLASSEMENT_CHANNEL_ID)
    if not channel:
        return

    embed = discord.Embed(
        title="🏆 Classement des vendeurs",
        color=0x5865F2,
        timestamp=datetime.now(),
    )

    if not vendeur_stats:
        embed.description = "Aucune commande traitée pour le moment."
    else:
        sorted_stats = sorted(vendeur_stats.items(), key=lambda x: x[1]["count"], reverse=True)
        medals = ["🥇", "🥈", "🥉"]
        classement = ""
        for i, (vid, vdata) in enumerate(sorted_stats):
            medal = medals[i] if i < 3 else f"`#{i+1}`"
            classement += f"{medal} **{vdata['nom']}** — {vdata['count']} commande(s)\n"
        embed.description = classement
        embed.set_footer(text=f"Total : {sum(v['count'] for v in vendeur_stats.values())} commande(s) traitée(s) • Mis à jour")

    try:
        if classement_message_id:
            try:
                msg = await channel.fetch_message(classement_message_id)
                await msg.edit(embed=embed)
            except discord.NotFound:
                msg = await channel.send(embed=embed)
                classement_message_id = msg.id
        else:
            # Supprimer les anciens messages du bot
            await channel.purge(limit=10, check=lambda m: m.author == guild.me)
            msg = await channel.send(embed=embed)
            classement_message_id = msg.id
    except Exception as e:
        print(f"❌ Erreur classement : {e}")


async def envoyer_logs(guild, channel, data, vendeur, transcript_lines, valide=True):
    log_channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
    if not log_channel:
        return

    ticket_num = data.get('ticket_num', 0)
    client_id = data.get('client_id')
    client_mention = f"<@{client_id}>" if client_id else "Non renseigné"
    nb_commandes = vendeur_stats.get(vendeur.id, {}).get("count", 0) if valide else 0
    statut_paiement = "✅ Validé" if valide else "❌ Non validé"

    recap = discord.Embed(
        title=f"Commande #{ticket_num:04d}",
        color=discord.Color.green() if valide else discord.Color.red(),
        timestamp=datetime.now(),
    )
    recap.add_field(name="Commande :", value=f"「🔥」commande-{ticket_num:04d}", inline=False)
    recap.add_field(name="Client :", value=client_mention, inline=True)
    recap.add_field(name="Vendeur :", value=vendeur.mention if valide else "Non renseigné", inline=True)
    recap.add_field(name="Moyens de paiement :", value=data.get('paiement', 'Non renseigné'), inline=True)
    recap.add_field(name="Statut du paiement :", value=statut_paiement, inline=True)
    recap.add_field(name="Nombre de commandes :", value=str(nb_commandes) if valide else "Non renseigné", inline=True)
    recap.add_field(name="Adresse :", value=data.get('adresse', 'Non renseigné'), inline=False)
    recap.add_field(name="Montant HT :", value=data.get('montant', 'Non renseigné'), inline=True)
    recap.add_field(name="Transcript :", value="voir le fichier joint", inline=True)

    transcript_text = "\n".join(transcript_lines) if transcript_lines else "Aucun message."
    file = discord.File(
        fp=io.BytesIO(transcript_text.encode("utf-8")),
        filename=f"commande-{ticket_num:04d}-transcript.txt"
    )
    try:
        await log_channel.send(embed=recap, file=file)
    except Exception as e:
        print(f"❌ Erreur logs : {e}")

async def recuperer_transcript(channel):
    transcript_lines = []
    try:
        async for msg in channel.history(limit=None, oldest_first=True):
            timestamp = msg.created_at.strftime("%d/%m/%Y %H:%M")
            if msg.content:
                transcript_lines.append(f"[{timestamp}] {msg.author.display_name}: {msg.content}")
            if msg.attachments:
                for att in msg.attachments:
                    transcript_lines.append(f"[{timestamp}] {msg.author.display_name} a envoyé: {att.url}")
            if msg.embeds:
                for emb in msg.embeds:
                    if emb.description:
                        transcript_lines.append(f"[{timestamp}] [EMBED] {emb.description[:300]}")
                    for field in emb.fields:
                        transcript_lines.append(f"[{timestamp}] [EMBED] {field.name}: {field.value.strip('`')}")
    except Exception as e:
        transcript_lines.append(f"Erreur : {e}")
    return transcript_lines

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
        if user.id in clients_en_cours:
            await interaction.followup.send("❌ Tu as déjà un ticket en cours ! Ferme-le avant d'en ouvrir un nouveau.", ephemeral=True)
            return
        ticket_counter["count"] += 1
        ticket_num = ticket_counter["count"]
        vendeur_role = discord.utils.get(guild.roles, name=VENDEUR_ROLE_NAME)
        category = discord.utils.get(guild.categories, name=CATEGORY_ATTENTE)
        channel_name = f"「🔥」Commande - {ticket_num:04d}"
        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            topic=f"Commande de {user.display_name} | N°{ticket_num:04d}",
        )
        await ticket_channel.edit(sync_permissions=True)
        await ticket_channel.set_permissions(user, view_channel=True, send_messages=True, read_message_history=True, attach_files=True)
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
            "vendeur_member": None,
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
        msg = await interaction.followup.send(f"✅ Ton ticket a été créé : {ticket_channel.mention}", ephemeral=True, wait=True)
        await asyncio.sleep(3)
        await msg.delete()

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
        await channel.edit(category=category_prise, overwrites=overwrites_prise(guild, client, vendeur, vendeur_role))
        if channel.id in ticket_data:
            ticket_data[channel.id]["vendeur"] = vendeur.display_name
            ticket_data[channel.id]["vendeur_member"] = vendeur.id
        if vendeur.id not in vendeur_stats:
            vendeur_stats[vendeur.id] = {"nom": vendeur.display_name, "count": 0}
        old_embed = interaction.message.embeds[0]
        new_embed = discord.Embed(description=old_embed.description, color=0x06C167)
        for field in old_embed.fields:
            if field.name == "Status":
                new_embed.add_field(name="Status", value=f"```Pris en charge (par {vendeur.display_name})```", inline=False)
            else:
                new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
        new_embed.set_image(url=IMAGE_URL)
        await interaction.message.edit(embed=new_embed, view=TicketActiveView(user_id=self.user_id))
        await interaction.followup.send(f"Commande attribuée à {vendeur.mention}.")

    @discord.ui.button(label="🔒 Fermer le ticket", style=discord.ButtonStyle.danger, custom_id="fermer_init")
    async def fermer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_vendeur(interaction):
            await interaction.response.send_message("❌ Tu dois avoir le rôle **Vendeur**.", ephemeral=True)
            return
        embed = discord.Embed(title="🔒 Ticket fermé", description=f"Fermé par {interaction.user.mention}. Suppression dans **5 minutes**.", color=0xED4245)
        await interaction.response.send_message(embed=embed)
        client_id = ticket_clients.pop(interaction.channel.id, None)
        clients_en_cours.discard(client_id)
        ticket_data.pop(interaction.channel.id, None)
        await asyncio.sleep(300)
        try:
            await interaction.channel.delete()
        except Exception:
            pass

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
        vendeur_role = discord.utils.get(guild.roles, name=VENDEUR_ROLE_NAME)
        client_id = ticket_clients.get(channel.id)
        client_mention = f"<@{client_id}>" if client_id else "Client"

        # Vérifier lien Uber Eats
        lien_trouve = False
        async for msg in channel.history(limit=100):
            if "ubereats.com/fr/orders/" in msg.content:
                lien_trouve = True
                break

        if not lien_trouve:
            category_traitee = discord.utils.get(guild.categories, name=CATEGORY_TRAITEE)
            client = guild.get_member(client_id) if client_id else None
            if category_traitee:
                await channel.edit(category=category_traitee, overwrites=overwrites_traitee(guild, client, vendeur, vendeur_role))
            old_embed = interaction.message.embeds[0]
            new_embed = discord.Embed(description=old_embed.description, color=discord.Color.red())
            for field in old_embed.fields:
                if field.name == "Status":
                    new_embed.add_field(name="Status", value="```Non validée (pas de lien Uber Eats)```", inline=False)
                else:
                    new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
            new_embed.set_image(url=IMAGE_URL)
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(embed=new_embed, view=self)
            await interaction.followup.send(f"Aucune commande n'a été enregistrée.")
            ticket_clients.pop(channel.id, None)
            clients_en_cours.discard(client_id)
            ticket_data.pop(channel.id, None)

            async def supprimer_non_valide():
                await asyncio.sleep(300)
                transcript_lines = await recuperer_transcript(channel)
                await envoyer_logs(guild, channel, data, vendeur, transcript_lines, valide=False)
                try:
                    await channel.delete()
                except Exception:
                    pass
            asyncio.ensure_future(supprimer_non_valide())
            return

        await interaction.response.defer()

        # Stats
        if vendeur.id not in vendeur_stats:
            vendeur_stats[vendeur.id] = {"nom": vendeur.display_name, "count": 0}
        vendeur_stats[vendeur.id]["count"] += 1
        vendeur_stats[vendeur.id]["nom"] = vendeur.display_name
        asyncio.ensure_future(mettre_a_jour_classement(guild))

        client = guild.get_member(client_id) if client_id else None
        category_traitee = discord.utils.get(guild.categories, name=CATEGORY_TRAITEE)
        if category_traitee:
            await channel.edit(category=category_traitee, overwrites=overwrites_traitee(guild, client, vendeur, vendeur_role))

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
        await interaction.message.edit(embed=new_embed, view=self)

        nb_commandes = vendeur_stats.get(vendeur.id, {}).get("count", 1)
        await interaction.followup.send(
            f"Merci {client_mention} ! Vous avez fait **{nb_commandes} commande(s)**. "
            f"N'hésitez pas à envoyer une photo de votre commande une fois reçue dans <#1507797858345287790>, ça nous aide énormément. "
            f"S'il y a un problème avec la commande, n'hésitez pas à mentionner votre vendeur {vendeur.mention}. À bientôt !"
        )

        ticket_clients.pop(channel.id, None)
        clients_en_cours.discard(client_id)
        ticket_data.pop(channel.id, None)

        async def supprimer_apres_delai():
            await asyncio.sleep(300)
            transcript_lines = await recuperer_transcript(channel)
            await envoyer_logs(guild, channel, data, vendeur, transcript_lines, valide=True)
            try:
                await channel.delete()
            except Exception:
                pass
        asyncio.ensure_future(supprimer_apres_delai())

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
    sorted_stats = sorted(vendeur_stats.items(), key=lambda x: x[1]["count"], reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    classement = ""
    for i, (vid, vdata) in enumerate(sorted_stats):
        medal = medals[i] if i < 3 else f"`#{i+1}`"
        classement += f"{medal} **{vdata['nom']}** — {vdata['count']} commande(s)\n"
    embed.add_field(name="Classement", value=classement or "Aucun", inline=False)
    embed.set_footer(text=f"Total : {sum(v['count'] for v in vendeur_stats.values())} commande(s) traitée(s)")
    await interaction.response.send_message(embed=embed)

# ───────────────────────────────────────────────
# EVENTS
# ───────────────────────────────────────────────
@bot.event
async def on_member_join(member):
    role = discord.utils.get(member.guild.roles, name="「🛎️」Client")
    if role:
        try:
            await member.add_roles(role)
        except Exception as e:
            print(f"❌ Erreur attribution rôle : {e}")


@bot.event
async def on_guild_channel_delete(channel):
    client_id = ticket_clients.pop(channel.id, None)
    if client_id:
        clients_en_cours.discard(client_id)
        ticket_data.pop(channel.id, None)

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
