-- What the reread read: the context exactly as the model got it (anonymous authors U1, U2…), and who each of them is, so that the owner can see on what a decision rests.
ALTER TABLE claim_rereads ADD COLUMN IF NOT EXISTS context text;
ALTER TABLE claim_rereads ADD COLUMN IF NOT EXISTS people jsonb;       -- {"U1": user id as text, …}
