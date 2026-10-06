-- Earlier analyses read only the beginning of long conversations. Requeue those
-- conversations once, while preserving the original messages and human reviews.
CREATE TEMP TABLE long_analysis_conversations ON COMMIT DROP AS
SELECT cm.conversation_id,
       coalesce(sum(length(m.content)) FILTER (WHERE analysis_substantive(m.content)), 0) AS embed_chars,
       coalesce(sum(length(m.content)), 0) AS extract_chars
FROM conversation_messages cm
JOIN messages m ON m.id = cm.message_id
GROUP BY cm.conversation_id;

DELETE FROM conversation_embeddings e
USING long_analysis_conversations c
WHERE e.conversation_id = c.conversation_id AND c.embed_chars > 6000;

DELETE FROM claims cl
USING long_analysis_conversations c
WHERE cl.conversation_id = c.conversation_id AND c.extract_chars > 7000
  AND cl.review_status = 'auto';

DELETE FROM conversation_extractions e
USING long_analysis_conversations c
WHERE e.conversation_id = c.conversation_id AND c.extract_chars > 7000;
