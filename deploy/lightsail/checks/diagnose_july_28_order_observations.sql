BEGIN TRANSACTION READ ONLY;

SELECT format(
    'observation=%s:phase=%s:state=%s:status=%s:price=%s:original=%s:matched=%s:remaining=%s:observed=%s',
    groups.template_id,
    observations.phase,
    observations.remote_state,
    observations.remote_status,
    observations.limit_price,
    observations.original_quantity,
    observations.matched_quantity,
    observations.remaining_quantity,
    observations.observed_at
)
FROM resolution_order_observations AS observations
JOIN resolution_order_groups AS groups
  ON groups.order_group_id = observations.order_group_id
WHERE groups.template_id IN (
    'numeric_threshold:earnings-hlt-2026q2:YES',
    'numeric_threshold:earnings-rcl-2026q2:YES',
    'numeric_threshold:earnings-ko-2026q2:YES',
    'numeric_threshold:earnings-pypl-2026q2:YES',
    'numeric_threshold:earnings-jblu-2026q2:YES',
    'numeric_threshold:earnings-ba-2026q2:NO'
)
ORDER BY observations.observed_at, groups.template_id;

ROLLBACK;
