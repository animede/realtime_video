// Use about two frames at 16 fps for the picture, but overlap the audible audio
// only at the very end of that interval.
window.crossfade = async function (oldVideo, nextVideo, duration = 140) {
  const audible = !nextVideo.muted;
  const audioFadeDuration = 24;
  nextVideo.volume = audible ? 0 : 1;
  nextVideo.style.opacity = '0';
  nextVideo.style.zIndex = '2';
  nextVideo.classList.add('active');
  await new Promise(resolve => requestAnimationFrame(resolve));
  nextVideo.style.opacity = '1';
  const started = performance.now();
  while (performance.now() - started < duration) {
    const elapsed = performance.now() - started;
    if (audible) {
      const audioRatio = Math.max(0, Math.min(1, (elapsed - duration + audioFadeDuration) / audioFadeDuration));
      nextVideo.volume = audioRatio;
      oldVideo.volume = 1 - audioRatio;
    }
    await new Promise(resolve => requestAnimationFrame(resolve));
  }
  nextVideo.volume = 1;
  oldVideo.volume = 1;
};

// Leave a small scheduling margin after the visual blend finishes.
window.watchBoundary = function (video) {
  const check = () => {
    if (video !== players[active] || video.paused || video.ended) return;
    const remaining = video.duration - video.currentTime;
    const next = window.latestRun?.plan.scenes[currentIndex + 1];
    if (remaining <= 0.16 && next?.status === 'ready' && !switching) {
      startScene(currentIndex + 1, window.latestRun);
      return;
    }
    if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(check);
    else setTimeout(check, 20);
  };
  if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(check);
  else setTimeout(check, 20);
};
