-- The role check no longer waits for three positions on an axis. Measured on the invented political server (tools/evaluate_scores.py), once the position of each claim is read
-- twice (analysis/stances.py): the sign of a person's score on an axis is the one that they were told in 93-94 % of the cases with a single proposition behind it, and in 96 % with
-- three; the interval of uncertainty (never narrower than 0.35, wide for a single remark) already keeps a verdict from being given on a whim. Waiting for 3 positions and a weight
-- of 1.5 left 88 % of the cases without a verdict for 2 points of precision. Only the values that were never changed are moved.
UPDATE scoring_settings SET value = 1 WHERE key = 'min_propositions' AND value = 3;
UPDATE scoring_settings SET value = 0.5 WHERE key = 'min_evidence_weight' AND value = 1.5;
