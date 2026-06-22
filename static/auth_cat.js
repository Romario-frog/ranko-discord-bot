(function () {
  const root = document.documentElement;
  const cat = document.getElementById('pixelCat');
  if (!cat) return;

  let mouseX = window.innerWidth / 2;
  let mouseY = window.innerHeight / 2;
  let x = 36;
  let y = Math.max(90, window.innerHeight - 104);
  let vx = 2.1;
  let vy = -1.15;
  let wobble = 0;
  const catSize = 64;
  const safe = 22;

  function setGradient(e) {
    mouseX = e.clientX;
    mouseY = e.clientY;
    const px = Math.round((mouseX / window.innerWidth) * 100);
    const py = Math.round((mouseY / window.innerHeight) * 100);
    root.style.setProperty('--mouse-x', px + '%');
    root.style.setProperty('--mouse-y', py + '%');
    root.style.setProperty('--hue', String(Math.round((mouseX / window.innerWidth) * 55 + 215)));
  }

  window.addEventListener('pointermove', setGradient, { passive: true });

  function tick() {
    const w = window.innerWidth;
    const h = window.innerHeight;
    const cx = x + catSize / 2;
    const cy = y + catSize / 2;
    const dx = cx - mouseX;
    const dy = cy - mouseY;
    const dist = Math.max(1, Math.hypot(dx, dy));

    if (dist < 230) {
      const force = (230 - dist) / 230;
      vx += (dx / dist) * force * 1.15;
      vy += (dy / dist) * force * 1.15;
      cat.classList.add('scared');
    } else {
      cat.classList.remove('scared');
      vx += Math.sin(wobble / 28) * 0.015;
      vy += Math.cos(wobble / 36) * 0.015;
    }

    vx *= 0.965;
    vy *= 0.965;

    const speed = Math.hypot(vx, vy);
    const maxSpeed = 8.5;
    if (speed > maxSpeed) {
      vx = (vx / speed) * maxSpeed;
      vy = (vy / speed) * maxSpeed;
    }

    x += vx;
    y += vy;

    if (x <= safe) { x = safe; vx = Math.abs(vx) + 0.8; }
    if (x >= w - catSize - safe) { x = w - catSize - safe; vx = -Math.abs(vx) - 0.8; }
    if (y <= safe) { y = safe; vy = Math.abs(vy) + 0.8; }
    if (y >= h - catSize - safe) { y = h - catSize - safe; vy = -Math.abs(vy) - 0.8; }

    wobble += 1;
    const flip = vx < 0 ? -1 : 1;
    const rot = Math.max(-7, Math.min(7, vx * 1.1));
    const bob = Math.sin(wobble / 7) * 2.4;
    cat.style.transform = `translate3d(${x}px, ${y + bob}px, 0) scaleX(${flip}) rotate(${rot}deg)`;

    requestAnimationFrame(tick);
  }

  setGradient({ clientX: mouseX, clientY: mouseY });
  tick();
})();
