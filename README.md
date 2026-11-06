# VIE Watch — alerte perso pour les offres VIE commerciales

Ce petit projet surveille automatiquement les pages carrières de plusieurs
entreprises (Air Liquide, Airbus, Decathlon, Renault Group, Sagemcom pour
commencer) et t'envoie une notification sur ton téléphone dès qu'une
nouvelle offre VIE dans le domaine commercial apparaît.

Il tourne gratuitement sur les serveurs de GitHub (GitHub Actions), donc
il continue de surveiller même quand ton ordinateur est éteint — c'est
la différence avec une solution qui dépendrait de ta machine.

Important : ce script **ne postule jamais à ta place**. Il te prévient le
plus vite possible, à toi de cliquer "Postuler" toi-même dès la notif reçue.

## Mise en place (une seule fois, ~15 minutes)

### 1. Créer un dépôt GitHub

Si tu n'as pas de compte GitHub : crée-en un gratuitement sur github.com.
Puis crée un nouveau dépôt (bouton "New repository"), par exemple nommé
`vie-watch`. Choisis-le **public** — le code ne contient aucune donnée
personnelle, et ça te donne des minutes d'exécution illimitées et
gratuites (un dépôt privé est limité à ~2000 minutes/mois sur le plan
gratuit, ce qui peut être juste avec un contrôle toutes les 30 minutes).

### 2. Ajouter les fichiers

Dans ton nouveau dépôt, utilise "Add file" → "Upload files" et dépose
tous les fichiers de ce dossier **en gardant l'arborescence** (en
particulier le dossier `.github/workflows/` doit rester à cet endroit
exact, sinon GitHub ne le détectera pas).

### 3. Créer ton canal de notification (ntfy)

Va sur https://ntfy.sh et choisis un nom de "topic" (canal) long et
difficile à deviner — par exemple `lucas-vie-watch-7f3k9d2a`. N'importe
qui connaissant ce nom peut lire tes notifications, donc évite un nom
trop simple comme `lucas-vie`.

Ensuite, sur ton téléphone : installe l'app gratuite **ntfy** (iOS/Android)
et abonne-toi à ce topic. Tu peux aussi juste ouvrir
`https://ntfy.sh/ton-topic` dans un navigateur pour tester.

### 4. Configurer le secret dans GitHub

Dans ton dépôt : Settings → Secrets and variables → Actions → "New
repository secret". Nom : `NTFY_TOPIC`. Valeur : le topic choisi à l'étape
3. Ça garde ton canal privé (pas visible dans le code public).

### 5. Activer et tester

Onglet "Actions" du dépôt → autorise les workflows si GitHub te le
demande → clique sur "VIE Watch" → "Run workflow" pour lancer un premier
test manuel. Regarde les logs : tu dois voir chaque entreprise vérifiée
et, la toute première fois, aucune alerte (normal, tout est considéré
"déjà vu" au premier passage — c'est à partir du deuxième contrôle que les
nouveautés seront détectées).

Une fois validé, le workflow tourne tout seul toutes les 30 minutes.

## Ce qui est fiable, ce qui l'est moins

- **Air Liquide, Airbus, Decathlon** : ces sites publient un sitemap listant
  chaque offre individuellement. La détection est fiable : nouvelle offre
  VIE + mot-clé commercial dans le titre → alerte.
- **Renault Group, Sagemcom** : ces pages n'exposent pas ce sitemap. Le
  script surveille le texte affiché autour du mot "VIE" et te prévient dès
  que ce texte change. C'est moins précis (tu recevras un extrait de texte
  brut plutôt qu'un titre de poste tout propre) mais ça te donne quand même
  l'alerte la plus rapide possible, avec le lien pour aller vérifier
  toi-même.

## Ajouter une autre entreprise

Ouvre `vie_watch.py`, repère la liste `COMPANIES` en haut du fichier, et
ajoute un bloc sur le même modèle. Cherche d'abord si l'entreprise a un
sitemap listant ses offres (souvent indiqué dans `robots.txt` du site
carrières, ligne "Sitemap:") — si oui, utilise `"type": "sitemap"`. Sinon,
utilise `"type": "playwright"` avec l'URL de recherche déjà filtrée si
possible (VIE, commercial, pays...).
