// The launch card is drawn locally so the graphic scales with the dashboard.
function drawLaunchCargo(canvas) {
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const w = canvas.clientWidth, h = canvas.clientHeight, dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  ctx.scale(dpr, dpr);
  const scale = Math.min(w * .42 / 139, h * .83 / 126, 1.55);
  const ox = w - 54 * scale, oy = h * .70;
  ctx.translate(ox, oy);
  ctx.scale(scale, scale);
  function polygon(vertices, fill, stroke, lineWidth = .85) {
    ctx.beginPath();
    vertices.forEach(([x,y], i) => i ? ctx.lineTo(x,y) : ctx.moveTo(x,y));
    if (fill) { ctx.closePath(); ctx.fillStyle = fill; ctx.fill(); }
    if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = lineWidth; ctx.stroke(); }
  }
  for(let i=-6;i<7;i++) {
    polygon([[-145, i*18+5],[100,i*18+128]],null,'#d6b5ff20',.65);
    polygon([[-145,i*18+125],[100,i*18+2]],null,'#d6b5ff20',.65);
  }
  function crate(x,y,size,height){
    const s=size, d=s*.49;
    const at=(a,b,c=0)=>[x+(a-b)*s,y+(a+b)*d-c*height];
    const face=(points,color,line='#dfcbfa99')=>polygon(points.map(p=>at(...p)),color,line);
    face([[0,0,1],[1,0,1],[1,1,1],[0,1,1]],'#bea2eb');
    face([[0,1,1],[1,1,1],[1,1,0],[0,1,0]],'#8465a8');
    face([[1,0,1],[1,1,1],[1,1,0],[1,0,0]],'#624b83');
    face([[.39,0,1],[.60,0,1],[.60,1,1],[.39,1,1]],'#d8c1f6','#d8c1f6aa');
    face([[.39,1,1],[.60,1,1],[.60,1,.74],[.39,1,.74]],'#bc9dd7',null);
    // Parcel label with individual barcode strokes.
    face([[1,.18,.74],[1,.49,.74],[1,.49,.39],[1,.18,.39]],'#dfcfeb',null);
    for(let k=0;k<6;k++)polygon([at(1,.218+k*.039,.67),at(1,.218+k*.039,.47)],null,'#705c85',k%3===0?1.3:.65);
    polygon([at(.15,1,.23),at(.32,1,.23)],null,'#d3bbe898',1);
    polygon([at(.15,1,.32),at(.26,1,.32)],null,'#d3bbe898',1);
  }
  crate(-35,8,27,27);
  crate(18,10,27,27);
  crate(-8,22,27,27);
  crate(-8,-6,27,27);
  crate(-8,-33.5,26.8,27);
  const fade=ctx.createLinearGradient(-125,0,-30,0);
  fade.addColorStop(0,'#41314fee');fade.addColorStop(1,'#41314f00');
  // The artwork fades before the timer, keeping the numerals legible on narrow cards.
  ctx.globalCompositeOperation='destination-out';
  ctx.fillStyle=fade;ctx.fillRect(-1000,-300,970,600);
}
