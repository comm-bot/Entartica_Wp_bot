import asyncio
from types import SimpleNamespace

import scripts.send_raipur_approved_draft as script
from app.services.raipur_draft_sender import ApprovedDraftSendResult


def _settings(**updates):
    values = dict(exotel_outbound_enabled=True, raipur_approved_draft_send_enabled=True,
                  raipur_outbound_test_recipients=("+910000000000",))
    values.update(updates)
    return SimpleNamespace(**values)


def _draft(**updates):
    values = dict(draft_status="approved", draft_metadata={"response_valid": True})
    values.update(updates)
    return values


class Sender:
    def __init__(self, result): self.result, self.calls = result, []
    async def send(self, draft_id, recipient, *, confirmed):
        self.calls.append((draft_id, recipient, confirmed))
        return self.result


def test_dry_run_is_dependency_free(monkeypatch, capsys):
    monkeypatch.setattr(script, "build_controlled_sender_dependencies", lambda: (_ for _ in ()).throw(AssertionError()))
    assert script.main(["--draft-id", "draft", "--to", "+910000000000"]) == 0
    assert capsys.readouterr().out == "mode=dry_run\nreason=dry_run\n"


def test_confirmed_branch_builds_once_calls_sender_and_maps_accepted(monkeypatch, capsys):
    result = ApprovedDraftSendResult(True, True, True, False, "accepted")
    sender, calls = Sender(result), []
    repo = SimpleNamespace(get_draft_by_id=lambda draft_id: calls.append(draft_id) or _draft())
    monkeypatch.setattr(script, "build_controlled_sender_dependencies", lambda: calls.append("builder") or (_settings(), repo, sender))
    assert script.main(["--draft-id", "draft", "--to", "+910000000000", "--confirm-send"]) == 0
    output = capsys.readouterr().out
    assert calls == ["builder", "draft"] and sender.calls == [("draft", "+910000000000", True)]
    assert "api_accepted=true" in output and "sid_recorded=true" in output and "message_sent=true" in output
    assert "+910000000000" not in output and "approved text" not in output


def test_sender_gates_and_duplicate_map_without_network(monkeypatch, capsys):
    for settings, result, expected in (
        (_settings(exotel_outbound_enabled=False), ApprovedDraftSendResult(False, False, False, False, "send_feature_disabled"), "configuration_ready=false"),
        (_settings(raipur_approved_draft_send_enabled=False), ApprovedDraftSendResult(False, False, False, False, "send_feature_disabled"), "configuration_ready=false"),
        (_settings(raipur_outbound_test_recipients=()), ApprovedDraftSendResult(False, False, False, False, "recipient_not_allowlisted"), "recipient_allowlisted=false"),
        (_settings(), ApprovedDraftSendResult(False, False, False, True, "duplicate_send_prevented"), "duplicate_send_prevented=true"),
    ):
        sender = Sender(result)
        repo = SimpleNamespace(get_draft_by_id=lambda draft_id: _draft())
        monkeypatch.setattr(script, "build_controlled_sender_dependencies", lambda settings=settings, repo=repo, sender=sender: (settings, repo, sender))
        assert script.main(["--draft-id", "draft", "--to", "+910000000000", "--confirm-send"]) == 1
        output = capsys.readouterr().out
        assert expected in output and "approved text" not in output and "sid-safe" not in output
        assert len(sender.calls) == 1


def test_reconciliation_result_is_safe_and_not_reported_as_a_duplicate(monkeypatch, capsys):
    result = ApprovedDraftSendResult(True, False, False, False, "reconciliation_required")
    sender = Sender(result)
    repo = SimpleNamespace(get_draft_by_id=lambda draft_id: _draft())
    monkeypatch.setattr(script, "build_controlled_sender_dependencies", lambda: (_settings(), repo, sender))

    assert script.main(["--draft-id", "draft", "--to", "+910000000000", "--confirm-send"]) == 1
    output = capsys.readouterr().out
    assert "send_attempted=true" in output
    assert "api_accepted=false" in output
    assert "sid_recorded=false" in output
    assert "duplicate_send_prevented=false" in output
    assert "message_sent=false" in output
    assert "reason=reconciliation_required" in output
    assert "+910000000000" not in output
