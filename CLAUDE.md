# Tierlist twenty one pilots

Appli web statique (index.html + songs.js) publiée sur GitHub Pages : https://sir-dori.github.io/top-tierlist/

## Règle : tester avant chaque envoi
Après toute modification, lancer `python3 tests/run_tests.py` et ne pousser (git push) que si tous les tests passent.
Quand on corrige un bug, ajouter d'abord un test qui le reproduit dans tests/run_tests.py.

Les tests utilisent un faux Spotify (réponses en retard, chanson jouée sous un autre identifiant) : aucun compte n'est nécessaire.
Prérequis : `pip install playwright && playwright install chromium`.

L'utilisateur n'est pas développeur : expliquer les changements simplement, en français.
