-- Provisional verdicts (docs/regles-du-bot.md, « Vérification sur Internet »): when no trusted source settles a claim, pages of other sources may give an opinion, **marked provisional**:
-- `likely_true` / `likely_false`, with the quotation that was verified on the page. They never ground a public correction nor a rating (only `confirmed`, `partly`, `contradicted` do).
ALTER TABLE debate_claims DROP CONSTRAINT IF EXISTS debate_claims_verdict_check;
ALTER TABLE debate_claims ADD CONSTRAINT debate_claims_verdict_check
    CHECK (verdict IN ('confirmed', 'contradicted', 'partly', 'disputed', 'likely_true', 'likely_false', 'unverifiable'));
ALTER TABLE debate_sources DROP CONSTRAINT IF EXISTS debate_sources_tier_check;
ALTER TABLE debate_sources ADD CONSTRAINT debate_sources_tier_check CHECK (tier IN ('official', 'checker', 'other'));
