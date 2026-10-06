"""The advisory locks of the database, in one place: two numbers that are equal are the same lock, so they are chosen here and nowhere else."""

# One migration at a time, whoever starts it (the app and the bot start together).
MIGRATION = 7_262_024

# Everything that rewrites the messages, the people and what is built from them takes this one: an import, the erasure of a person, the building of the conversations.
# They touch the same rows (an erasure removes the conversations of a person, the building cuts them), so they wait for each other. The ingestion and the building
# have always been the same lock, by accident of two equal numbers; it is now said, and tested (tests/test_locks.py).
DATA = 7_262_025

# Starting a debate checks how many are open (per person, per server) and then adds one: two commands at the same moment must not both pass the check.
DEBATE = 7_262_026
