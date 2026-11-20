"""Episode export plan: Buddhist-Era date and the per-version D revision number."""
import asyncio

from cutdeck import honekasae_export as he


def test_episode_date_is_ddmmyy_buddhist_era(tmp_path):
    assert he.episode_date(tmp_path / "20261120 - โหนกระแส") == "201169"
    assert he.episode_date(tmp_path / "20260101 - โหนกระแส") == "010169"


def test_d_counts_per_version(tmp_path):
    day = tmp_path / "20261118 - โหนกระแส"
    exports = day / "5. EXPORTS"
    exports.mkdir(parents=True)
    for name in ("FB D1", "FB D2", "FB D3", "YT D1", "REEL 3M D1", "REEL 1M D1", "REEL 1M D2"):
        (exports / f"โหนกระแส 181169 {name}.mp4").write_bytes(b"")
    (exports / "โหนกระแส 181169 FB D9.mov").write_bytes(b"")      # not an mp4: ignored
    (exports / "โหนกระแส 171169 YT D7.mp4").write_bytes(b"")      # other date: ignored
    names = {j["version"]: j["output_file"].rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
             for j in he.plan(day, list(he.VERSIONS))}
    assert names == {"YT": "โหนกระแส 181169 YT D2.mp4", "FB": "โหนกระแส 181169 FB D4.mp4",
                     "REEL 3M": "โหนกระแส 181169 REEL 3M D2.mp4", "REEL 1M": "โหนกระแส 181169 REEL 1M D3.mp4"}


def test_first_export_is_d1_and_each_job_names_its_sequence(tmp_path):
    day = tmp_path / "20261120 - โหนกระแส"
    (day / "5. EXPORTS").mkdir(parents=True)
    jobs = he.plan(day, ["YT", "REEL 1M"])
    assert [j["sequence_name"] for j in jobs] == ["1 YOUTUBE D1", "4 REEL SIZE D1"]
    assert jobs[0]["output_file"].endswith("โหนกระแส 201169 YT D1.mp4")


def test_run_queues_each_version_in_ame_by_sequence_name(tmp_path):
    calls = []

    class FakeBackend:
        async def premiere(self, command, args):
            calls.append((command, args))
            return {"resolved": True, "queue_started": True}

    jobs = [{"version": "FB", "sequence_name": "2 FACEBOOK D1", "output_file": str(tmp_path / "fb.mp4")},
            {"version": "YT", "sequence_name": "1 YOUTUBE D1", "output_file": str(tmp_path / "yt.mp4")}]
    out = asyncio.run(he.run(jobs, tmp_path / "BAS4.epr", FakeBackend()))
    assert calls == [
        ("export_sequence", {"output_file": str(tmp_path / "fb.mp4"), "preset_file": str(tmp_path / "BAS4.epr"),
                             "queue": "ame", "sequence_name": "2 FACEBOOK D1", "start": False}),
        ("export_sequence", {"output_file": str(tmp_path / "yt.mp4"), "preset_file": str(tmp_path / "BAS4.epr"),
                             "queue": "ame", "sequence_name": "1 YOUTUBE D1", "start": True})]
    assert [o["version"] for o in out] == ["FB", "YT"]
