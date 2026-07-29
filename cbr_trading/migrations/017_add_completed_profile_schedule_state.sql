-- Add a distinct successful terminal state to the additive profile lifecycle.
-- Existing rows, columns, states, and event history remain unchanged.

ALTER TABLE resolution_profile_schedules
    DROP CONSTRAINT IF EXISTS
        resolution_profile_schedules_state_check,
    ADD CONSTRAINT resolution_profile_schedules_state_check
        CHECK (
            state IN (
                'PENDING',
                'PREFLIGHTING',
                'READY',
                'ACTIVE',
                'COMPLETED',
                'EXPIRED',
                'BLOCKED'
            )
        );

ALTER TABLE resolution_profile_schedule_events
    DROP CONSTRAINT IF EXISTS
        resolution_profile_schedule_events_previous_state_check,
    DROP CONSTRAINT IF EXISTS
        resolution_profile_schedule_events_next_state_check,
    ADD CONSTRAINT
        resolution_profile_schedule_events_previous_state_check
        CHECK (
            previous_state IS NULL
            OR previous_state IN (
                'PENDING',
                'PREFLIGHTING',
                'READY',
                'ACTIVE',
                'COMPLETED',
                'EXPIRED',
                'BLOCKED'
            )
        ),
    ADD CONSTRAINT
        resolution_profile_schedule_events_next_state_check
        CHECK (
            next_state IN (
                'PENDING',
                'PREFLIGHTING',
                'READY',
                'ACTIVE',
                'COMPLETED',
                'EXPIRED',
                'BLOCKED'
            )
        );
