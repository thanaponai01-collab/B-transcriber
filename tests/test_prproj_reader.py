"""prproj_reader walks the object graph shapes seen in real .prproj files (2026-09-25)."""

import gzip

from cutdeck.prproj_reader import read_project

T = 254016000000  # Premiere ticks per second

PROJECT = f"""<?xml version="1.0" encoding="UTF-8" ?>
<PremiereData Version="3">
  <Sequence ObjectUID="seq-1">
    <MarkerOwner><Markers ObjectRef="10"/></MarkerOwner>
    <TrackGroups>
      <TrackGroup Index="0"><First>v</First><Second ObjectRef="20"/></TrackGroup>
      <TrackGroup Index="1"><First>a</First><Second ObjectRef="21"/></TrackGroup>
    </TrackGroups>
    <Name>Main</Name>
  </Sequence>
  <Markers ObjectID="10">
    <Markers><Marker Index="0"><First>g</First><Second ObjectRef="11"/></Marker></Markers>
  </Markers>
  <Marker ObjectID="11">
    <DVAMarker>{{"DVAMarker":{{"mStartTime":{{"ticks":{2 * T}}},"mType":"Comment","mName":"hi"}}}}</DVAMarker>
  </Marker>
  <VideoTrackGroup ObjectID="20"><TrackGroup><Tracks><Track Index="0" ObjectURef="vt"/></Tracks></TrackGroup></VideoTrackGroup>
  <AudioTrackGroup ObjectID="21"><TrackGroup><Tracks><Track Index="0" ObjectURef="at"/></Tracks></TrackGroup></AudioTrackGroup>
  <VideoClipTrack ObjectUID="vt"><ClipTrack><Track><Index>0</Index><IsLocked>false</IsLocked><IsMuted>false</IsMuted></Track>
    <ClipItems><TrackItems><TrackItem Index="0" ObjectRef="30"/></TrackItems></ClipItems></ClipTrack></VideoClipTrack>
  <AudioClipTrack ObjectUID="at"><ClipTrack><Track><Index>0</Index><IsLocked>true</IsLocked></Track>
    <ClipItems><TrackItems><TrackItem Index="0" ObjectRef="40"/></TrackItems></ClipItems></ClipTrack>
    <AudioTrack><ComponentOwner><Components ObjectRef="50"/></ComponentOwner></AudioTrack></AudioClipTrack>
  <AudioComponentChain ObjectID="50"><ComponentChain><Components><Component Index="0" ObjectRef="51"/></Components></ComponentChain></AudioComponentChain>
  <AudioFader ObjectID="51"><AudioComponent><Component><Params><Param Index="0" ObjectRef="52"/></Params></Component></AudioComponent></AudioFader>
  <AudioComponentParam ObjectID="52"><CurrentValue>true</CurrentValue><Name>Mute</Name></AudioComponentParam>
  <VideoClipTrackItem ObjectID="30"><ClipTrackItem>
    <ComponentOwner><Components ObjectRef="31"/></ComponentOwner>
    <TrackItem><End>{3 * T}</End></TrackItem><SubClip ObjectRef="32"/></ClipTrackItem></VideoClipTrackItem>
  <VideoComponentChain ObjectID="31"><ComponentChain><Components><Component Index="0" ObjectRef="33"/></Components></ComponentChain></VideoComponentChain>
  <VideoFilterComponent ObjectID="33"><Component><DisplayName>Tint</DisplayName><Bypass>true</Bypass></Component>
    <MatchName>AE.ADBE Tint</MatchName></VideoFilterComponent>
  <SubClip ObjectID="32"><Clip ObjectRef="34"/><Name>shot.mp4</Name></SubClip>
  <VideoClip ObjectID="34"><Clip><Source ObjectRef="35"/><InPoint>{T}</InPoint><OutPoint>{4 * T}</OutPoint></Clip></VideoClip>
  <VideoMediaSource ObjectID="35"><MediaSource><Media ObjectURef="m1"/></MediaSource></VideoMediaSource>
  <Media ObjectUID="m1"><ActualMediaFilePath>C:\\shot.mp4</ActualMediaFilePath></Media>
  <AudioClipTrackItem ObjectID="40"><ClipTrackItem>
    <ComponentOwner><Components ObjectRef="41"/></ComponentOwner>
    <TrackItem><Start>{T}</Start><End>{2 * T}</End></TrackItem><SubClip ObjectRef="42"/><IsMuted>true</IsMuted></ClipTrackItem></AudioClipTrackItem>
  <AudioComponentChain ObjectID="41"><ComponentChain><Components><Component Index="0" ObjectRef="43"/></Components></ComponentChain></AudioComponentChain>
  <AudioFilterComponent ObjectID="43"><AudioComponent><Component><DisplayName>Hard Limiter</DisplayName><Bypass>false</Bypass></Component></AudioComponent></AudioFilterComponent>
  <SubClip ObjectID="42"><Clip ObjectRef="44"/><Name>Nested</Name></SubClip>
  <AudioClip ObjectID="44"><Clip><Source ObjectRef="45"/><InPoint>0</InPoint><OutPoint>{T}</OutPoint></Clip></AudioClip>
  <AudioSequenceSource ObjectID="45"><SequenceSource><Sequence ObjectURef="seq-1"/></SequenceSource></AudioSequenceSource>
</PremiereData>"""


def test_reads_tracks_clips_effects_and_markers(tmp_path):
    path = tmp_path / "p.prproj"
    path.write_bytes(gzip.compress(PROJECT.encode()))

    (seq,) = read_project(path)["sequences"]

    assert seq["name"] == "Main"
    assert seq["markers"] == [{"time": 2.0, "type": "Comment", "name": "hi", "comment": None}]

    (vt,) = seq["video_tracks"]
    assert (vt["muted"], vt["locked"]) == (False, False)
    assert vt["clips"] == [{
        "name": "shot.mp4", "start": 0.0, "end": 3.0, "source_in": 1.0, "source_out": 4.0,
        "disabled": False, "media_path": "C:\\shot.mp4",
        "effects": [{"name": "Tint", "match_name": "AE.ADBE Tint", "bypass": True}],
    }]

    (at,) = seq["audio_tracks"]
    assert (at["muted"], at["locked"]) == (True, True)
    (clip,) = at["clips"]
    assert clip["nested_sequence"] == "Main"
    assert clip["disabled"] is True
    assert clip["effects"] == [{"name": "Hard Limiter", "match_name": None, "bypass": False}]


def test_reads_uncompressed_xml(tmp_path):
    path = tmp_path / "p.prproj"
    path.write_text(PROJECT, encoding="utf-8")
    assert read_project(path)["sequences"][0]["name"] == "Main"
