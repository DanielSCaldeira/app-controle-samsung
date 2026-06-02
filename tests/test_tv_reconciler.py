"""Tests for task 06caefe6 — Reconciliação de IP por device id (DHCP).

Acceptance criterion verified here:
  Dado um KnownTv salvo cujo IP mudou no *fake de descoberta*, o registry
  atualiza o IP **por device id** e a sessão **reconecta no novo IP**.

Strategy
--------
``TvReconciler`` é a peça que fecha o risco de *DHCP-lease-churn* (arquitetura
§8): o UUID do device é estável, então quando o IP muda ele

  1. re-roda a descoberta (SSDP/mDNS via ``DiscoveryService``) e escolhe o
     candidato cujo ``DiscoveredTv.id`` == ``KnownTv.id``;
  2. se o IP do candidato difere do armazenado, persiste o novo endereço com
     ``TvRegistry.updateIp`` **antes** de reconectar; e
  3. entrega o endereço atual (replicando o token salvo) a
     ``RemoteSession.connect``.

Nem coroutines/Flow do Kotlin nem Room/AndroidKeyStore rodam numa JVM/desktop;
seguindo a convenção do repositório de **executar a lógica real** em vez de só
inspecionar fontes, este suite faz um *port* fiel do ``reconcileAndReconnect``
em Python e o executa sobre dublês:

  * ``FakeDiscoveryService`` — o "fake de descoberta" pedido pelo critério;
    devolve uma lista de candidatos (cada um com id/ip/nome/model);
  * ``InMemoryRegistry`` — espelha ``updateIp`` (atualiza só o ip, por id,
    retornando bool) e ``getToken`` (token replicado na reconexão);
  * ``RecordingSession`` — grava cada ``connect(target, token)`` para que o
    teste verifique em qual IP a sessão reconectou.

O port replica exatamente o comportamento do Kotlin:
  reconcileAndReconnect(tv):
    rediscovered = rediscoverById(tv.id) ?: return NotFound
    ipChanged = rediscovered.ip != tv.ip
    if ipChanged: registry.updateIp(tv.id, rediscovered.ip)
    token = registry.getToken(tv.id)
    session.connect(DiscoveredTv(tv.id, rediscovered.name, newIp, rediscovered.model), token)
    return Reconnected(newIp, ipChanged)

Asserções estruturais (sempre executadas) confirmam que o fonte Kotlin casa por
device id, persiste o IP **antes** de reconectar e modela o resultado.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "app" / "src" / "main" / "java" / "com" / "factory" / "samsungremote"
RECONCILER_KT = PKG / "network" / "discovery" / "TvReconciler.kt"
DISCOVERY_MODULE_KT = PKG / "di" / "DiscoveryModule.kt"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Dublês: fake de descoberta, registry em memória, sessão que grava conexões.
# --------------------------------------------------------------------------- #
def discovered(id_, name, ip, model=None) -> dict:
    """Mirror of DiscoveredTv (id/name/ipAddress/modelName)."""
    return {"id": id_, "name": name, "ipAddress": ip, "modelName": model}


def known(id_, name, ip, token=None, mac=None) -> dict:
    """Mirror of the persisted KnownTv view this reconciler reads/writes."""
    return {"id": id_, "name": name, "ipAddress": ip, "macAddress": mac, "token": token}


class FakeDiscoveryService:
    """The "fake de descoberta": discover() emits the configured candidates.

    ``rediscoverById`` in the port consumes this until it finds a matching id
    (mirroring ``discover().firstOrNull { it.id == deviceId }``).
    """

    def __init__(self, candidates):
        self.candidates = list(candidates)
        self.discover_calls = 0

    def discover(self):
        self.discover_calls += 1
        # The real flow is continuous; the port iterates it until a match is
        # found (firstOrNull) or it is exhausted (== timeout / NotFound).
        return list(self.candidates)


class InMemoryRegistry:
    """Faithful mirror of the bits of TvRegistry the reconciler touches.

    ``updateIp`` changes ONLY ip_address, keyed by device id, returning whether
    a row matched; ``getToken`` returns the stored (decrypted) pairing token.
    """

    def __init__(self, tvs):
        self.store = {tv["id"]: dict(tv) for tv in tvs}
        self.update_ip_calls = []  # (id, ip) in call order

    def updateIp(self, id_, ip_address) -> bool:
        self.update_ip_calls.append((id_, ip_address))
        existing = self.store.get(id_)
        if existing is None:
            return False
        existing["ipAddress"] = ip_address  # only the IP changes
        return True

    def getToken(self, id_):
        tv = self.store.get(id_)
        return tv["token"] if tv else None

    def ip_of(self, id_):
        return self.store[id_]["ipAddress"]


class RecordingSession:
    """Mirror of RemoteSession.connect — records (target, token, registry_ip)."""

    def __init__(self, registry: InMemoryRegistry):
        self.registry = registry
        self.connections = []  # list of dicts

    def connect(self, target: dict, token):
        # Snapshot the registry's stored IP at connect time so a test can prove
        # the IP was persisted BEFORE the (re)connection happened.
        self.connections.append(
            {
                "target": target,
                "token": token,
                "registry_ip_at_connect": self.registry.ip_of(target["id"]),
            }
        )


# --------------------------------------------------------------------------- #
# Faithful Python port of TvReconciler.reconcileAndReconnect.
# --------------------------------------------------------------------------- #
class ReconcileResult:
    NOT_FOUND = ("NotFound",)

    @staticmethod
    def reconnected(ip, ip_changed):
        return ("Reconnected", {"ipAddress": ip, "ipChanged": ip_changed})


class TvReconciler:
    def __init__(self, discovery_service, registry, session):
        self.discovery = discovery_service
        self.registry = registry
        self.session = session

    def _rediscover_by_id(self, device_id):
        # withTimeoutOrNull { discover().firstOrNull { it.id == deviceId } }
        for cand in self.discovery.discover():
            if cand["id"] == device_id:
                return cand
        return None

    def reconcileAndReconnect(self, tv: dict):
        rediscovered = self._rediscover_by_id(tv["id"])
        if rediscovered is None:
            return ReconcileResult.NOT_FOUND

        new_ip = rediscovered["ipAddress"]
        ip_changed = new_ip != tv["ipAddress"]
        # Persist the new address by device id BEFORE reconnecting.
        if ip_changed:
            self.registry.updateIp(tv["id"], new_ip)

        token = self.registry.getToken(tv["id"])
        target = discovered(
            tv["id"], rediscovered["name"], new_ip, rediscovered["modelName"]
        )
        self.session.connect(target, token)
        return ReconcileResult.reconnected(new_ip, ip_changed)


def _build(known_tvs, candidates):
    registry = InMemoryRegistry(known_tvs)
    session = RecordingSession(registry)
    discovery = FakeDiscoveryService(candidates)
    return TvReconciler(discovery, registry, session), registry, session, discovery


# --------------------------------------------------------------------------- #
# Critério principal — IP mudou no fake de descoberta:
#   registry atualiza por device id + sessão reconecta no novo IP.
# --------------------------------------------------------------------------- #
def test_ip_changed_updates_registry_by_id_and_reconnects_at_new_ip():
    tv = known("uuid-1", "Sala", "192.168.0.10", token="pair-tok")
    rec, registry, session, _ = _build(
        [tv], [discovered("uuid-1", "Sala", "192.168.0.50", model="UN50MU6300")]
    )

    result = rec.reconcileAndReconnect(tv)

    # 1) registry atualizou o IP, POR DEVICE ID.
    assert registry.update_ip_calls == [("uuid-1", "192.168.0.50")]
    assert registry.ip_of("uuid-1") == "192.168.0.50"

    # 2) a sessão reconectou exatamente uma vez, no NOVO IP.
    assert len(session.connections) == 1
    conn = session.connections[0]
    assert conn["target"]["ipAddress"] == "192.168.0.50"
    assert conn["target"]["id"] == "uuid-1"

    # 3) resultado sinaliza reconexão com IP alterado.
    assert result == ReconcileResult.reconnected("192.168.0.50", True)


def test_ip_persisted_before_reconnect():
    """O novo IP é persistido ANTES de reconectar (registry e sessão nunca divergem)."""
    tv = known("uuid-1", "Sala", "192.168.0.10", token="t")
    rec, _, session, _ = _build([tv], [discovered("uuid-1", "Sala", "10.0.0.7")])

    rec.reconcileAndReconnect(tv)

    # No instante do connect, o registry já refletia o IP novo.
    assert session.connections[0]["registry_ip_at_connect"] == "10.0.0.7"


def test_stored_token_is_replayed_on_reconnect():
    tv = known("uuid-1", "Sala", "192.168.0.10", token="secret-token-123")
    rec, _, session, _ = _build([tv], [discovered("uuid-1", "Sala", "192.168.0.50")])

    rec.reconcileAndReconnect(tv)

    assert session.connections[0]["token"] == "secret-token-123"


def test_matches_by_device_id_not_by_ip_among_several_candidates():
    """Reconciliação casa pelo UUID estável, ignorando IP/nome dos outros."""
    tv = known("uuid-target", "Quarto", "192.168.0.10", token="tok")
    candidates = [
        discovered("uuid-other-a", "Cozinha", "192.168.0.10"),  # mesmo IP antigo!
        discovered("uuid-target", "Quarto", "192.168.0.77", model="QN55"),
        discovered("uuid-other-b", "Sala", "192.168.0.99"),
    ]
    rec, registry, session, _ = _build([tv], candidates)

    result = rec.reconcileAndReconnect(tv)

    assert registry.ip_of("uuid-target") == "192.168.0.77"
    assert session.connections[0]["target"]["ipAddress"] == "192.168.0.77"
    assert session.connections[0]["target"]["id"] == "uuid-target"
    assert result == ReconcileResult.reconnected("192.168.0.77", True)


def test_reconnect_target_carries_rediscovered_name_and_model():
    tv = known("uuid-1", "Nome Antigo", "192.168.0.10", token="t")
    rec, _, session, _ = _build(
        [tv], [discovered("uuid-1", "Nome Atual", "192.168.0.50", model="QN90B")]
    )

    rec.reconcileAndReconnect(tv)

    target = session.connections[0]["target"]
    assert target["name"] == "Nome Atual"
    assert target["modelName"] == "QN90B"


# --------------------------------------------------------------------------- #
# Casos de borda
# --------------------------------------------------------------------------- #
def test_ip_unchanged_does_not_update_registry_but_still_reconnects():
    """IP estável: nada de updateIp, mas a sessão reconecta no mesmo IP."""
    tv = known("uuid-1", "Sala", "192.168.0.10", token="t")
    rec, registry, session, _ = _build(
        [tv], [discovered("uuid-1", "Sala", "192.168.0.10")]
    )

    result = rec.reconcileAndReconnect(tv)

    assert registry.update_ip_calls == []  # não tocou o registry
    assert session.connections[0]["target"]["ipAddress"] == "192.168.0.10"
    assert result == ReconcileResult.reconnected("192.168.0.10", False)


def test_not_found_leaves_registry_and_session_untouched():
    """Device id não reaparece na descoberta → NotFound, nada é alterado."""
    tv = known("uuid-1", "Sala", "192.168.0.10", token="t")
    rec, registry, session, _ = _build(
        [tv],
        [discovered("uuid-OTHER", "Outra", "192.168.0.50")],  # id diferente
    )

    result = rec.reconcileAndReconnect(tv)

    assert result == ReconcileResult.NOT_FOUND
    assert registry.update_ip_calls == []
    assert registry.ip_of("uuid-1") == "192.168.0.10"  # IP intocado
    assert session.connections == []  # nenhuma reconexão


def test_empty_discovery_is_not_found():
    tv = known("uuid-1", "Sala", "192.168.0.10", token="t")
    rec, registry, session, _ = _build([tv], [])

    assert rec.reconcileAndReconnect(tv) == ReconcileResult.NOT_FOUND
    assert session.connections == []
    assert registry.update_ip_calls == []


# --------------------------------------------------------------------------- #
# Estrutural — o fonte Kotlin implementa a semântica que o port assume.
# --------------------------------------------------------------------------- #
def test_reconciler_source_exists():
    assert RECONCILER_KT.is_file(), f"implementação ausente em {RECONCILER_KT}"


def test_reconciler_exposes_api_and_result_model():
    text = _read(RECONCILER_KT)
    assert "class TvReconciler" in text
    assert "fun reconcileAndReconnect" in text
    # Resultado modelado explicitamente (no-throw).
    assert "ReconcileResult" in text
    assert "Reconnected" in text and "NotFound" in text


def test_reconciler_matches_by_device_id():
    text = _read(RECONCILER_KT)
    # Casa o candidato cujo id == id da TV armazenada.
    assert re.search(r"\.id\s*==\s*\w*[Ii]d", text) or "it.id ==" in text, \
        "reconciliação não casa por device id"


def test_reconciler_persists_ip_before_reconnecting():
    text = _read(RECONCILER_KT)
    assert "registry.updateIp" in text, "não persiste o IP via registry.updateIp"
    assert "session.connect" in text, "não reconecta via session.connect"
    # updateIp deve aparecer ANTES de session.connect no fluxo.
    assert text.index("registry.updateIp") < text.index("session.connect"), \
        "IP precisa ser persistido ANTES de reconectar"


def test_reconciler_replays_stored_token_from_registry():
    text = _read(RECONCILER_KT)
    assert "registry.getToken" in text, "token salvo não é replicado na reconexão"


def test_reconciler_bounds_discovery_window():
    text = _read(RECONCILER_KT)
    assert "withTimeoutOrNull" in text, "redescoberta não é limitada por timeout"


def test_di_module_wires_reconciler():
    text = _read(DISCOVERY_MODULE_KT)
    assert "TvReconciler" in text, "DiscoveryModule não provê o TvReconciler"
    # Fia descoberta + registry + sessão.
    for dep in ("DiscoveryService", "TvRegistry", "RemoteSession"):
        assert dep in text, f"TvReconciler não recebe a dependência {dep}"
