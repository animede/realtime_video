// A single uninterrupted audio element is the playback clock. Generated clip
// audio is muted, and visual transitions do not shorten the logical timeline.
const masterAudio = document.querySelector('#master-audio');
const embeddedStartScene = window.startScene;
const embeddedWatchBoundary = window.watchBoundary;
const embeddedResetPlayback = window.resetPlayback;
const embeddedPlayNext = window.playNext;
let masterRunId = null;

function usesMasterAudio(run) {
  return Boolean(run?.audio_url);
}

function sceneStartTime(run, index) {
  return run.plan.scenes.slice(0, index).reduce((total, scene) => total + scene.duration, 0);
}

async function prepareMasterAudio(run) {
  if (!usesMasterAudio(run)) return false;
  if (masterRunId !== run.id) {
    masterAudio.src = run.audio_url;
    masterAudio.load();
    masterRunId = run.id;
  }
  players.forEach(video => { video.muted = true; });
  return true;
}

window.crossfade = async function (oldVideo, nextVideo, duration = 140) {
  nextVideo.style.opacity = '0';
  nextVideo.style.zIndex = '2';
  nextVideo.classList.add('active');
  await new Promise(resolve => requestAnimationFrame(resolve));
  nextVideo.style.opacity = '1';
  await wait(duration);
};

window.startScene = async function (index, run) {
  if (!usesMasterAudio(run)) return embeddedStartScene(index, run);
  const scene = run.plan.scenes[index];
  if (!scene || scene.status !== 'ready' || switching) return false;
  switching = true;
  const first = currentIndex < 0;
  const nextSlot = first ? active : 1 - active;
  const nextVideo = players[nextSlot];
  const oldVideo = first ? null : players[active];
  try {
    await prepareMasterAudio(run);
    loadScene(nextVideo, scene);
    await canRender(nextVideo);
    const startAt = sceneStartTime(run, index);
    const localTime = Math.max(0, masterAudio.currentTime - startAt);
    if (localTime > 0.04) nextVideo.currentTime = Math.min(localTime, Math.max(0, nextVideo.duration - 0.04));
    await nextVideo.play();
    if (first) {
      masterAudio.currentTime = startAt;
      try {
        await masterAudio.play();
      } catch (error) {
        if (error.name !== 'NotAllowedError') throw error;
        masterAudio.muted = true;
        soundButton.textContent = '音声をオン';
        await masterAudio.play();
      }
      nextVideo.style.zIndex = '1';
      nextVideo.classList.add('active');
    } else {
      oldVideo.pause(); // retain its final displayed frame under the fade
      await crossfade(oldVideo, nextVideo);
    }
    if (oldVideo) {
      oldVideo.classList.remove('active');
      oldVideo.style.opacity = '';
      oldVideo.style.zIndex = '0';
      oldVideo.removeAttribute('src');
      oldVideo.removeAttribute('data-scene');
      oldVideo.load();
    }
    nextVideo.style.opacity = '';
    nextVideo.style.zIndex = '1';
    active = nextSlot;
    currentIndex = index;
    played.add(index);
    document.querySelector('#empty').hidden = true;
    document.querySelector('#players').hidden = false;
    document.querySelector('#now-playing').textContent = `${String(index + 1).padStart(2, '0')} — ${scene.title}`;
    preloadNext(run);
    watchBoundary(nextVideo);
    return true;
  } catch (error) {
    document.querySelector('#buffer-state').textContent = `再生準備エラー: ${error.message}`;
    return false;
  } finally {
    switching = false;
  }
};

window.watchBoundary = function (video) {
  const run = window.latestRun;
  if (!usesMasterAudio(run)) return embeddedWatchBoundary(video);
  const check = () => {
    if (video !== players[active]) return;
    const nextIndex = currentIndex + 1;
    const next = window.latestRun?.plan.scenes[nextIndex];
    if (!next) return;
    const boundary = sceneStartTime(window.latestRun, nextIndex);
    if (masterAudio.currentTime >= boundary && next.status === 'ready' && !switching) {
      startScene(nextIndex, window.latestRun);
      return;
    }
    const expected = Math.max(0, masterAudio.currentTime - sceneStartTime(window.latestRun, currentIndex));
    if (Math.abs(video.currentTime - expected) > 0.12 && expected < video.duration) video.currentTime = expected;
    requestAnimationFrame(check);
  };
  requestAnimationFrame(check);
};

// An encoded clip can be a little shorter than its planned scene duration.
// Hold its last frame; only the master audio clock may advance the scene.
window.playNext = function () {
  if (usesMasterAudio(window.latestRun)) return;
  embeddedPlayNext();
};

window.resetPlayback = function () {
  masterAudio.pause();
  masterAudio.removeAttribute('src');
  masterAudio.load();
  masterRunId = null;
  embeddedResetPlayback();
};

soundButton.onclick = function () {
  const run = window.latestRun;
  if (!usesMasterAudio(run)) return toggleSound();
  masterAudio.muted = !masterAudio.muted;
  soundButton.textContent = masterAudio.muted ? '音声をオン' : '音声をオフ';
  if (!masterAudio.muted && currentIndex >= 0) masterAudio.play().catch(() => {});
};
