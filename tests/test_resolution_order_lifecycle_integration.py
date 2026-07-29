from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from cbr_trading.application import (
    CoordinationStatus,
    ResolutionTradingCoordinator,
)
from cbr_trading.client import DiscoveryResult
from cbr_trading.domain import (
    ExecutionStatus,
    OrderSide,
    PlacedOrder,
)
from cbr_trading.execution import (
    CancellationResult,
    CbrWarmPreparedExecutorAdapter,
    OrderGroupRecord,
    OrderGroupStatus,
    OrderInspectionResult,
    OrderObservation,
    PersistentOrderSupervisor,
    RemoteOrderSnapshot,
    RemoteOrderState,
    SupervisedPreparedExecutor,
    SupervisionClaim,
    SupervisionStatus,
    TickSizeChange,
    TickSizeChangeDetector,
    TickSizeObservationSource,
    TickSizeWatch,
    cbr_preparation_context,
    registration_from_handle,
)
from cbr_trading.live.account_repository import TradingAccountRecord
from cbr_trading.live.idempotency import ExecutionClaim
from cbr_trading.live.market import MarketSnapshot
from cbr_trading.live.market_channel import PolymarketMarketChannel
from cbr_trading.live.runner_executor import WarmLiveOrderExecutor
from cbr_trading.live.safety import LiveSafetySettings
from cbr_trading.sources import CbrResolutionSource
from cbr_trading.strategies import CbrRateDecisionStrategy


CONDITION_ID = "0x" + ("a" * 64)
WALLET = "0x" + ("b" * 40)
RELEASE_URL = "https://www.cbr.ru/eng/press/pr/?file=release"
OBSERVED_AT = datetime(
    2026,
    7,
    24,
    13,
    30,
    tzinfo=timezone.utc,
)


def _subscription() -> dict:
    return {
        "id": 17,
        "rule_key": "cbr_cut",
        "account_name": "primary",
        "condition_id": CONDITION_ID,
        "order_qty": 10,
        "order_price": "0.51",
        "params": {
            "threshold": -10,
            "cmp": "<=",
            "decision_mode": "binary_yes_no",
            "order_price_yes": "0.999",
            "order_price_no": "0.95",
            "order_lifecycle": {
                "kind": "reprice_on_tick_change",
                "old_tick": "0.01",
                "new_tick": "0.001",
                "max_reprices": 1,
            },
        },
    }


def _release() -> DiscoveryResult:
    return DiscoveryResult(
        ok=True,
        reason="published",
        url=RELEASE_URL,
        request_url=f"{RELEASE_URL}&_ts=1",
        status_code=200,
        content_type="text/html",
        title="Bank of Russia cuts the key rate to 14.25% p.a.",
        new_rate=14.25,
        published_at="2026-07-24T13:30:00Z",
    )


class _DiscoveryClient:
    def __init__(self):
        self.calls = 0

    def run_once(self) -> DiscoveryResult:
        self.calls += 1
        return _release()


class _AccountRepository:
    def __init__(self):
        self.closed = False

    def load_active(self, account_name: str) -> TradingAccountRecord:
        return TradingAccountRecord(
            name="primary",
            wallet_address=WALLET,
            venue="polymarket_clob",
            is_active=True,
            signature_type=2,
            encrypted_private_key=b"encrypted",
        )

    def close(self) -> None:
        self.closed = True


class _ExecutionLedger:
    def __init__(self):
        self.completions: list[dict] = []
        self.closed = False

    def ensure_ready(self) -> None:
        return None

    def reserve_many(self, *, release_url: str, intents) -> tuple:
        return tuple(
            ExecutionClaim(
                acquired=True,
                idempotency_key=f"integration:{index}",
                claim_id=index + 1,
            )
            for index, _ in enumerate(intents)
        )

    def complete(self, **kwargs: object) -> None:
        self.completions.append(dict(kwargs))

    def close(self) -> None:
        self.closed = True


class _MarketGateway:
    def load_snapshot(
        self,
        *,
        condition_id: str,
        outcome: str,
    ) -> MarketSnapshot:
        return MarketSnapshot(
            condition_id=condition_id,
            question="Will the Bank of Russia cut its key rate?",
            outcome=outcome,
            token_id=f"asset-{outcome.lower()}",
            best_bid=Decimal("0.50"),
            best_ask=None,
            last_trade_price=Decimal("0.50"),
            tick_size=Decimal("0.01"),
            minimum_order_size=Decimal("5"),
            neg_risk=False,
        )


class _Venue:
    def __init__(self):
        self.orders: dict[str, dict] = {}
        self.initial_posts: list[str] = []
        self.cancel_calls: list[tuple[str, ...]] = []
        self.replacement_requests: list[object] = []
        self._next_id = 1

    def place(
        self,
        *,
        asset_id: str,
        price: Decimal,
        quantity: Decimal,
    ) -> str:
        order_id = f"order-{self._next_id}"
        self._next_id += 1
        self.orders[order_id] = {
            "asset_id": asset_id,
            "price": price,
            "quantity": quantity,
            "state": RemoteOrderState.OPEN,
        }
        return order_id


class _TradingClient:
    wallet = WALLET
    wallet_type = "GNOSIS_SAFE"

    def __init__(self, venue: _Venue):
        self.venue = venue
        self.signed_orders: list[object] = []
        self.closed = False

    def get_balance_allowance(self, *, asset_type: str) -> object:
        return SimpleNamespace(balance="100000000")

    def create_limit_order(self, **kwargs: object) -> object:
        signed = SimpleNamespace(
            token_id=str(kwargs["token_id"]),
            order_type="GTC",
            post_only=bool(kwargs["post_only"]),
            price=str(kwargs["price"]),
            size=str(kwargs["size"]),
        )
        self.signed_orders.append(signed)
        return signed

    def post_orders(self, signed_orders) -> tuple:
        responses = []
        for signed in signed_orders:
            order_id = self.venue.place(
                asset_id=signed.token_id,
                price=Decimal(signed.price),
                quantity=Decimal(signed.size),
            )
            self.venue.initial_posts.append(order_id)
            responses.append(
                SimpleNamespace(
                    ok=True,
                    order_id=order_id,
                    status="LIVE",
                )
            )
        return tuple(responses)

    def close(self) -> None:
        self.closed = True


class _StatefulOrderGroupRepository:
    def __init__(self):
        self.group: OrderGroupRecord | None = None
        self.observations: tuple[OrderObservation, ...] = ()
        self.closed = False

    def register(self, handle, *, policy, metadata=None) -> OrderGroupRecord:
        self.group = OrderGroupRecord(
            registration=registration_from_handle(
                handle,
                policy=policy,
                metadata=metadata,
            ),
            status=OrderGroupStatus.ACTIVE,
            revision=0,
            reprice_count=0,
            live_order_ids=handle.live_order_ids,
        )
        return self.group

    def load_active_for_asset(
        self,
        asset_id: str,
    ) -> tuple[OrderGroupRecord, ...]:
        if (
            self.group is None
            or self.group.status != OrderGroupStatus.ACTIVE
            or self.group.registration.asset_id != asset_id
        ):
            return ()
        return (self.group,)

    def claim_tick_size_change(
        self,
        *,
        order_group_id: str,
        event: TickSizeChange,
    ) -> SupervisionClaim:
        if (
            self.group is None
            or self.group.registration.order_group_id != order_group_id
            or self.group.status != OrderGroupStatus.ACTIVE
        ):
            return SupervisionClaim(
                event_id=event.event_id,
                order_group_id=order_group_id,
                acquired=False,
                reason="order_group_not_active",
            )
        registration = self.group.registration
        if (
            registration.trigger_old_tick != event.old_tick
            or registration.trigger_new_tick != event.new_tick
        ):
            return SupervisionClaim(
                event_id=event.event_id,
                order_group_id=order_group_id,
                acquired=False,
                reason="tick_transition_mismatch",
            )
        revision = self.group.revision + 1
        self.group = replace(
            self.group,
            status=OrderGroupStatus.REPRICING,
            revision=revision,
        )
        return SupervisionClaim(
            event_id=event.event_id,
            order_group_id=order_group_id,
            acquired=True,
            revision=revision,
        )

    def complete_reprice(
        self,
        claim: SupervisionClaim,
        *,
        cancelled_order_ids,
        replacement_orders,
        filled_order_ids=(),
        observations=(),
    ) -> None:
        if (
            self.group is None
            or claim.revision != self.group.revision
            or self.group.status != OrderGroupStatus.REPRICING
        ):
            raise RuntimeError("supervision claim is no longer current")
        replacements = tuple(replacement_orders)
        self.observations = tuple(observations)
        self.group = replace(
            self.group,
            status=OrderGroupStatus.COMPLETED,
            revision=self.group.revision + 1,
            reprice_count=self.group.reprice_count + 1,
            live_order_ids=tuple(
                order.order_id
                for order in replacements
            ),
        )

    def record_replacement_submission(
        self,
        claim: SupervisionClaim,
        *,
        replacement_orders,
        parent_order_ids,
    ) -> None:
        if (
            self.group is None
            or claim.revision != self.group.revision
            or self.group.status != OrderGroupStatus.REPRICING
        ):
            raise RuntimeError("supervision claim is no longer current")

    def fail_claim(
        self,
        claim: SupervisionClaim,
        *,
        error: str,
        cancelled_order_ids=(),
        filled_order_ids=(),
        replacement_orders=(),
        observations=(),
    ) -> None:
        if self.group is not None:
            self.group = replace(
                self.group,
                status=OrderGroupStatus.FAILED,
                revision=self.group.revision + 1,
                last_error=error,
            )

    def close(self) -> None:
        self.closed = True


class _SupervisionGateway:
    def __init__(self, venue: _Venue):
        self.venue = venue
        self.closed = False

    def inspect_orders(
        self,
        *,
        account_name: str,
        order_ids,
    ) -> OrderInspectionResult:
        normalized = tuple(order_ids)
        return OrderInspectionResult(
            requested_order_ids=normalized,
            snapshots=tuple(
                self._snapshot(order_id)
                for order_id in normalized
            ),
        )

    def cancel_orders(
        self,
        *,
        account_name: str,
        order_ids,
    ) -> CancellationResult:
        normalized = tuple(order_ids)
        self.venue.cancel_calls.append(normalized)
        for order_id in normalized:
            self.venue.orders[order_id]["state"] = (
                RemoteOrderState.CANCELLED
            )
        return CancellationResult(
            requested_order_ids=normalized,
            cancelled_order_ids=normalized,
        )

    def place_replacement(self, request) -> tuple[PlacedOrder, ...]:
        self.venue.replacement_requests.append(request)
        assert request.quantity is not None
        order_id = self.venue.place(
            asset_id=request.asset_id,
            price=request.limit_price,
            quantity=request.quantity,
        )
        return (
            PlacedOrder(
                order_id=order_id,
                asset_id=request.asset_id,
                effective_price=request.limit_price,
                quantity=request.quantity,
            ),
        )

    def close(self) -> None:
        self.closed = True

    def _snapshot(self, order_id: str) -> RemoteOrderSnapshot:
        order = self.venue.orders[order_id]
        return RemoteOrderSnapshot(
            order_id=order_id,
            condition_id=CONDITION_ID,
            asset_id=order["asset_id"],
            side=OrderSide.BUY,
            limit_price=order["price"],
            original_quantity=order["quantity"],
            matched_quantity=Decimal("0"),
            state=order["state"],
            remote_status=order["state"].value,
            observed_at=OBSERVED_AT,
        )


class _MarketSubscription:
    def __init__(self, events: tuple[object, ...]):
        self._events = iter(events)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self) -> object:
        try:
            return next(self._events)
        except StopIteration:
            raise StopAsyncIteration from None

    async def close(self) -> None:
        self.closed = True


class _PublicMarketClient:
    def __init__(self, events: tuple[object, ...]):
        self.subscription = _MarketSubscription(events)
        self.spec = None
        self.closed = False

    async def subscribe(self, spec: object) -> _MarketSubscription:
        self.spec = spec
        return self.subscription

    async def close(self) -> None:
        self.closed = True


def _book_event() -> object:
    level = lambda price: SimpleNamespace(price=price, size="10")
    return SimpleNamespace(
        type="book",
        payload=SimpleNamespace(
            token_id="asset-yes",
            tick_size=None,
            bids=(level("0.99"),),
            asks=(level("0.999"),),
            timestamp=OBSERVED_AT,
        ),
    )


class ResolutionOrderLifecycleIntegrationTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_book_tick_reprices_prepared_order_to_desired_price(
        self,
    ) -> None:
        subscription = _subscription()
        venue = _Venue()
        trading_client = _TradingClient(venue)
        ledger = _ExecutionLedger()
        account_repository = _AccountRepository()
        legacy_executor = WarmLiveOrderExecutor(
            subscriptions=(subscription,),
            database_url="postgresql://unused",
            safety=LiveSafetySettings(
                trading_enabled=True,
                post_only=False,
                allowed_account="primary",
                max_order_quantity=Decimal("10"),
                max_notional=Decimal("10"),
                max_total_notional=Decimal("10"),
                accounts_master_key="test-master-key",
            ),
            account_repository=account_repository,
            market_gateway=_MarketGateway(),
            ledger=ledger,
            client_factory=(
                lambda private_key, wallet: trading_client
            ),
            decryptor=lambda encrypted, key: "private-key",
        )
        group_repository = _StatefulOrderGroupRepository()
        supervision_gateway = _SupervisionGateway(venue)
        supervisor = PersistentOrderSupervisor(
            repository=group_repository,
            gateway=supervision_gateway,
        )
        executor = SupervisedPreparedExecutor(
            CbrWarmPreparedExecutorAdapter(legacy_executor),
            supervisor=supervisor,
        )
        source = CbrResolutionSource(
            _DiscoveryClient(),
            previous_rate_provider=lambda: Decimal("14.5"),
            clock=lambda: OBSERVED_AT,
        )
        strategy = CbrRateDecisionStrategy((subscription,))
        context = cbr_preparation_context(RELEASE_URL)
        coordinator = ResolutionTradingCoordinator(
            source=source,
            strategies=(strategy,),
            executor=executor,
            context=context,
        )
        self.addCleanup(supervisor.close)
        self.addCleanup(coordinator.close)

        preparation = coordinator.prepare()
        outcome = coordinator.poll_once()

        self.assertTrue(preparation.ready)
        self.assertEqual(outcome.status, CoordinationStatus.COMPLETED)
        self.assertEqual(len(outcome.order_results), 1)
        initial = outcome.order_results[0]
        self.assertEqual(initial.status, ExecutionStatus.SUBMITTED)
        self.assertEqual(
            initial.orders[0].effective_price,
            Decimal("0.99"),
        )
        self.assertEqual(
            initial.handle.desired_price,
            Decimal("0.999"),
        )
        self.assertEqual(
            [order.price for order in trading_client.signed_orders],
            ["0.99", "0.95"],
        )
        self.assertIsNotNone(group_repository.group)
        assert group_repository.group is not None
        self.assertEqual(
            group_repository.group.status,
            OrderGroupStatus.ACTIVE,
        )

        registration = group_repository.group.registration
        detector = TickSizeChangeDetector(
            (
                TickSizeWatch(
                    asset_id=registration.asset_id,
                    old_tick=registration.trigger_old_tick,
                    new_tick=registration.trigger_new_tick,
                ),
            )
        )
        public_client = _PublicMarketClient(
            (_book_event(), _book_event())
        )
        channel = PolymarketMarketChannel(
            detector=detector,
            supervisor=supervisor,
            client_factory=lambda: public_client,
            clock=lambda: OBSERVED_AT,
        )

        dispatches = await channel.run()

        self.assertEqual(len(dispatches), 1)
        dispatch = dispatches[0]
        self.assertEqual(
            dispatch.event.source,
            TickSizeObservationSource
            .MARKET_CHANNEL_BOOK_LEVEL.value,
        )
        self.assertEqual(
            dispatch.results[0].status,
            SupervisionStatus.REPLACED,
        )
        initial_order_id = initial.orders[0].order_id
        replacement_order_id = (
            dispatch.results[0].replacement_order_ids[0]
        )
        self.assertEqual(
            venue.cancel_calls,
            [(initial_order_id,)],
        )
        self.assertEqual(
            venue.orders[initial_order_id]["state"],
            RemoteOrderState.CANCELLED,
        )
        self.assertEqual(
            venue.orders[replacement_order_id]["state"],
            RemoteOrderState.OPEN,
        )
        self.assertEqual(
            venue.orders[replacement_order_id]["price"],
            Decimal("0.999"),
        )
        request = venue.replacement_requests[0]
        self.assertEqual(request.limit_price, Decimal("0.999"))
        self.assertEqual(request.tick_size, Decimal("0.001"))
        self.assertEqual(
            request.replaced_order_ids,
            (initial_order_id,),
        )
        assert group_repository.group is not None
        self.assertEqual(
            group_repository.group.status,
            OrderGroupStatus.COMPLETED,
        )
        self.assertEqual(group_repository.group.reprice_count, 1)
        self.assertEqual(
            group_repository.group.live_order_ids,
            (replacement_order_id,),
        )
        self.assertEqual(group_repository.observations, ())
        self.assertEqual(
            tuple(public_client.spec.token_ids),
            ("asset-yes",),
        )
        self.assertTrue(public_client.subscription.closed)
        self.assertTrue(public_client.closed)


if __name__ == "__main__":
    unittest.main()
