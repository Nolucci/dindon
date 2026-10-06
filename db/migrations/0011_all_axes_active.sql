-- All 21 axes are active (decision of 2026-10-04). The seed (seed-axes.sql) never changes a row that exists, so a database made before this
-- decision needs this: the 9 extension axes were inactive. An axis that someone switches off afterwards stays off (this runs once).
UPDATE axes SET is_active = true WHERE NOT is_active;
