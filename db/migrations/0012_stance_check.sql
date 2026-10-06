-- The position (for / against / nuanced) that the model gave to a claim was often the reverse of what the person wrote: it judged whether the SUBJECT is approved
-- ("the 49.3 is anti-democratic" -> against) instead of whether the person agrees with the PROPOSITION. A second, narrow reading (analysis/stances.py) compares
-- the person's own words with the proposition and decides. `stance_before` keeps what the first reading said (a trace, and a way to measure it),
-- `stance_check` the version of the second reading (null: not read yet).
ALTER TABLE claims ADD COLUMN IF NOT EXISTS stance_check text;
ALTER TABLE claims ADD COLUMN IF NOT EXISTS stance_before smallint;
