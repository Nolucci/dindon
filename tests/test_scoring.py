"""The score and the verification with the roles, on invented people.

Numbers come from the specification (section 8): the SQL function must give them again.
"""
import pytest

from synthetic import World


@pytest.fixture
def world(conn):
    return World(conn)


def _activate(conn, axis_code: str) -> None:
    # The extension axes are inactive until the user has reviewed them; the test does it, then rolls back
    conn.execute("UPDATE axes SET is_active = true WHERE code = %s", (axis_code,))


# ---------------------------------------------------------------------------------------------
# The numbers of the specification
# ---------------------------------------------------------------------------------------------


def test_three_positions_against_the_positive_pole(world):
    person = world.person("alice")
    for text, confidence in (("p1", 0.81), ("p2", 0.72), ("p3", 0.72)):
        world.claim(person, world.proposition(text, {"economie": 1.0}), stance=-1, confidence=confidence)
    world.refresh_scores()
    score, uncertainty, weight, n = world.score(person, "economie")
    assert (score, uncertainty, weight, n) == (-0.692, 0.381, 2.250, 3)


def test_three_positions_with_different_weights(world):
    person = world.person("alice")
    # weights 0.81 / 0.425 / 0.72: the second one is a proposition that weighs 0.5 on the axis
    for text, confidence, loading in (("p1", 0.81, 1.0), ("p2", 0.85, 0.5), ("p3", 0.72, 1.0)):
        world.claim(person, world.proposition(text, {"economie": loading}), stance=-1, confidence=confidence)
    world.refresh_scores()
    score, uncertainty, weight, n = world.score(person, "economie")
    assert (score, uncertainty, weight, n) == (-0.662, 0.399, 1.955, 3)


def test_one_remark_never_gives_a_firm_score(world):
    person = world.person("alice")
    world.claim(person, world.proposition("p1", {"economie": 1.0}), stance=-1, confidence=1.0)
    world.refresh_scores()
    score, uncertainty, _, _ = world.score(person, "economie")
    assert abs(score) <= 0.5 and uncertainty >= 0.35


def test_inactive_axes_are_not_scored(world):
    person = world.person("alice")
    world.claim(person, world.proposition("p1", {"europe": 1.0}), stance=1, confidence=0.9)
    world.refresh_scores()
    assert world.score(person, "europe") is None


def test_a_rejected_claim_changes_the_score_and_the_last_one_removes_it(world):
    person = world.person("alice")
    claims = [
        world.claim(person, world.proposition(f"p{i}", {"economie": 1.0}), stance=-1, confidence=0.8)
        for i in range(3)
    ]
    world.refresh_scores()
    before = world.score(person, "economie")
    world.conn.execute("UPDATE claims SET review_status = 'rejected' WHERE id = %s", (claims[0],))
    world.refresh_scores()
    after = world.score(person, "economie")
    assert after[3] == 2 and after[2] < before[2]
    for claim_id in claims[1:]:
        world.conn.execute("UPDATE claims SET review_status = 'rejected' WHERE id = %s", (claim_id,))
    world.refresh_scores()
    assert world.score(person, "economie") is None


# ---------------------------------------------------------------------------------------------
# Verification with the roles that people gave themselves
# ---------------------------------------------------------------------------------------------


def _eurosceptic_claims(world, person, n=3):
    """n positions of someone who wants less Europe: a proposition that weighs -1 on 'europe', approved."""
    for i in range(n):
        world.claim(person, world.proposition(f"Quitter l'UE {i}", {"europe": -1.0}), stance=1, confidence=0.8)


def test_a_consistent_eurosceptic_is_concordant(world, conn):
    _activate(conn, "europe")
    person = world.person("alice", roles=("Eurosceptique",))
    _eurosceptic_claims(world, person)
    world.refresh_scores()
    assert world.verdicts(person) == {"Eurosceptique": "concordant"}


def test_a_europhile_role_with_the_opposite_claims_is_discordant(world, conn):
    _activate(conn, "europe")
    person = world.person("bob", roles=("Européiste",))
    _eurosceptic_claims(world, person)
    world.refresh_scores()
    assert world.verdicts(person) == {"Européiste": "discordant"}


def test_a_role_without_proof_is_not_verifiable(world):
    person = world.person("carol", roles=("Communiste",))
    world.refresh_scores()
    assert world.verdicts(person) == {"Communiste": "not_verifiable"}


def test_roles_that_contradict_each_other_are_spotted(world):
    person = world.person("dave", roles=("Protectionnisme", "Mondialiste", "Humaniste"))
    assert world.conflicts(person) == {frozenset({"protectionnisme", "mondialiste"})}


def test_few_positions_are_not_enough_to_check(world, conn):
    _activate(conn, "europe")
    person = world.person("erin", roles=("Européiste",))
    _eurosceptic_claims(world, person, n=1)
    world.refresh_scores()
    assert world.verdicts(person) == {"Européiste": "not_verifiable"}


# ---------------------------------------------------------------------------------------------
# Roles of age or gender are recognized only to be left out
# ---------------------------------------------------------------------------------------------


def test_age_and_gender_roles_are_never_used(world, conn):
    person = world.person("frank", roles=("Entre 16 et 20 ans", "Homme", "Femme", "Ping Annonces", "Eurosceptique"))
    kinds = dict(
        conn.execute("SELECT name, kind FROM classified_roles WHERE guild_id = %s", (world.guild_id,)).fetchall()
    )
    assert kinds["Entre 16 et 20 ans"] == "age" and kinds["Homme"] == "genre" and kinds["Femme"] == "genre"
    assert kinds["Ping Annonces"] == "notification" and kinds["Eurosceptique"] == "ideologie"
    claimed = conn.execute(
        "SELECT role_name FROM claimed_ideologies WHERE guild_id = %s AND user_id = %s", (world.guild_id, person)
    ).fetchall()
    assert claimed == [("Eurosceptique",)]
