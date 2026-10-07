-- Keep raw Discord messages, but exclude the suspended-account placeholder from
-- the material sent to the models and from the cheap substantive-message test.
CREATE OR REPLACE FUNCTION analysis_clean_text(content text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT trim(regexp_replace(regexp_replace(regexp_replace(regexp_replace(
        coalesce(content, ''),
        'One message removed from a suspended account[.]?', ' ', 'gi'),
        'https?://\S+', ' ', 'g'), '<a?:\w+:\d+>', ' ', 'g'), '\s+', ' ', 'g'))
$$;

-- Previously computed results are retained until an administrator explicitly
-- rebuilds the analysis. A migration must not silently erase reviewed work.
