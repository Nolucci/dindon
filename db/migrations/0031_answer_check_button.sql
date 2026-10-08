-- Dindon's answers (docs/regles-du-bot.md, « Répondre d'abord, chercher ensuite »): the message that carries an answer now says that it is not reliable and has one button, « Vérifier ».
-- A click asks for a deeper search on the Internet (`search_requested_at`); it replaces the votes Valide / Invalide, which stay in their table for the messages posted before.
-- `basis`: what the answer rests on: `model` (what the local model knows) or `pages` (a quotation from a page that is not a trusted source: only a first opinion).
ALTER TABLE debate_answers ADD COLUMN IF NOT EXISTS search_requested_at timestamptz;
ALTER TABLE debate_answers ADD COLUMN IF NOT EXISTS basis text NOT NULL DEFAULT 'model' CHECK (basis IN ('model', 'pages'));
