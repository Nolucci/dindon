-- A debate can be opened from one of the axes of Dindon (docs/DEBAT.md): when nobody knows what to debate, the person picks an axis in the popup and Dindon asks the question of that axis,
-- which people answer by choosing one of its two poles (« Fédéral » or « Unitaire », or « Ne sait pas »).
--
-- `axis` is a copy of what was shown, taken when the debate opens: {"code": "structure", "name": "Structure de l'État", "for": "Fédéral", "against": "Unitaire"}. The axes can be renamed or switched
-- off later without changing the buttons of a debate that is already running. Null: a debate on a subject written by the person (answers: pour / ne sait pas / contre).
-- No foreign key (like the other debate tables), and nothing here is about a person.
ALTER TABLE debates ADD COLUMN IF NOT EXISTS axis jsonb CHECK (axis IS NULL OR jsonb_typeof(axis) = 'object');
