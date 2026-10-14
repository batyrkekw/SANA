// Original inline SVG artwork. Kept as vectors so wings can move independently.
export function birdMarkup({ animated = false } = {}) {
  const wing = 'M310 259C287 246 272 222 255 197C241 177 225 165 197 156C126 133 63 94 27 39C35 110 81 159 163 179C108 176 62 156 32 130C48 182 95 214 163 216C126 227 89 227 63 216C85 257 132 279 193 253C166 281 132 294 104 291C137 323 182 320 223 286C208 317 184 337 162 344C198 365 239 340 263 306C253 338 239 356 224 369C271 365 299 325 306 286Z';
  return `<svg class="sana-bird${animated ? ' bird--animated' : ''}" viewBox="0 0 640 440" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">
    <g class="bird-figure" fill="currentColor">
      <path class="bird-wing-left" d="${wing}"/>
      <g transform="translate(640 0) scale(-1 1)"><path class="bird-wing-right" d="${wing}"/></g>
      <path class="bird-body" d="M279 239C299 238 308 223 319 199C330 174 342 157 362 156C373 155 382 158 390 162C400 161 412 164 422 168C397 178 383 192 380 213C377 235 385 253 371 284C361 307 349 326 347 346C347 367 373 390 400 406C382 420 366 420 355 408C344 397 336 382 331 369C336 396 346 417 358 430L326 448C315 429 310 406 308 384C306 407 300 430 288 448L257 429C269 414 280 395 287 369C280 386 270 403 258 413C247 422 233 420 215 407C242 387 268 365 271 345C275 324 257 294 260 274C261 258 268 247 279 239Z" transform="translate(8 -21)"/>
      <circle cx="373" cy="148" r="4.1" fill="#101f32"/>
    </g>
  </svg>`;
}

function student(x, y, { flip = false, coat = '#dfc995', book = false } = {}) {
  return `<g transform="translate(${x} ${y})${flip ? ' scale(-1 1)' : ''}">
    <path d="M-25 82L-31 137H-12L2 88L14 137H32L23 77" fill="#172b3c"/>
    <path d="M-29 137H-9V143H-35Q-36 138-29 137M14 137H32L38 143H14Z" fill="#ecdfc5"/>
    <path d="M-18 8Q0 0 18 10L29 80Q1 92-29 81Z" fill="${coat}"/>
    <path d="M-6 5V-6H8V8Q1 15-6 5" fill="#bc856b"/>
    <path d="M-16-25Q-16-45 2-44Q21-44 19-23L17-9Q5 2-9-9Z" fill="#dba98a"/>
    <path d="M-16-18Q-28-41-7-49Q10-54 23-39L21-23L13-26L9-35Q-3-30-12-31L-12-16Z" fill="#172b3c"/>
    <circle cx="10" cy="-21" r="1.4" fill="#172b3c"/>
    <path d="M9-12L14-13" stroke="#92614e" stroke-width="1.5" stroke-linecap="round"/>
    ${book ? '<path d="M-20 42L3 36L29 42L24 71L1 66L-22 73Z" fill="#f3e8cf" stroke="#9eac9d" stroke-width="2"/><path d="M3 36L1 66" stroke="#9eac9d" stroke-width="2"/><path d="M-18 17L-29 49L-19 57M19 17L32 45L23 53" fill="none" stroke="'+coat+'" stroke-width="13" stroke-linecap="round"/><path d="M-20 55L-14 55M24 51L19 53" stroke="#dba98a" stroke-width="8" stroke-linecap="round"/>' : '<path d="M-17 17L-28 55L-15 70M18 17L34 42L59 28" fill="none" stroke="'+coat+'" stroke-width="14" stroke-linecap="round"/><path d="M57 29L64 23M-15 70L-11 74" stroke="#dba98a" stroke-width="8" stroke-linecap="round"/>'}
  </g>`;
}

function mathScene(page) {
  const panels = [
    '<text x="301" y="107" font-size="31" text-anchor="middle">x² − 5x + 6 = 0</text><text x="301" y="143" font-size="18" text-anchor="middle" opacity=".75">a = 1 · b = −5 · c = 6</text><rect x="275" y="182" width="52" height="38" rx="5" fill="#e7d5af" fill-opacity=".13" stroke="#e7d5af" stroke-width="1.5"/><path d="M285 182V173A16 16 0 0 1 317 173V182" stroke="#e7d5af" stroke-width="2" fill="none"/><circle cx="301" cy="198" r="4"/><path d="M301 201V208" stroke="#e7d5af" stroke-width="2"/>',
    '<text x="301" y="103" font-size="28" text-anchor="middle">D = b² − 4ac</text><text x="301" y="143" font-size="25" text-anchor="middle">D = 25 − 24 = 1</text><path d="M290 168L251 191M311 168L350 191" stroke="#e7d5af" stroke-width="1.5"/><text x="242" y="217" font-size="26" text-anchor="middle">x₁</text><text x="359" y="217" font-size="26" text-anchor="middle">x₂</text><text x="301" y="178" font-size="17" text-anchor="middle" opacity=".7">D &gt; 0</text>',
    '<text x="220" y="111" font-size="29">x =</text><text x="330" y="95" font-size="26" text-anchor="middle">−b ± √D</text><path d="M263 106H397" stroke="#e7d5af" stroke-width="1.5"/><text x="330" y="135" font-size="26" text-anchor="middle">2a</text><rect x="190" y="169" width="103" height="48" rx="8" fill="#e7d5af" fill-opacity=".1"/><rect x="311" y="169" width="103" height="48" rx="8" fill="#e7d5af" fill-opacity=".1"/><text x="241" y="200" font-size="26" text-anchor="middle">x₁ = 2</text><text x="363" y="200" font-size="26" text-anchor="middle">x₂ = 3</text>',
    '<text x="301" y="102" font-size="25" text-anchor="middle">2² − 5 · 2 + 6 = 0</text><text x="301" y="143" font-size="25" text-anchor="middle">3² − 5 · 3 + 6 = 0</text><text x="301" y="207" font-size="23" text-anchor="middle">(x − 2)(x − 3) = 0</text><path d="M421 89L427 96L438 81M421 130L427 137L438 122" fill="none" stroke="#b7cca6" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
  ];
  return `<rect width="560" height="340" fill="#243c50"/>
    <path d="M0 276H560V340H0Z" fill="#1d3042"/><path d="M0 277H560" stroke="#9aacb0" stroke-opacity=".2"/>
    <rect x="143" y="45" width="321" height="207" rx="8" fill="#172e3d" stroke="#7b8c88" stroke-width="3"/>
    <rect x="153" y="55" width="301" height="187" rx="3" fill="none" stroke="#a8b8ac" stroke-opacity=".1"/>
    <g fill="#e7d5af" font-family="Georgia, serif">${panels[Math.min(page, 3)]}</g>
    <path d="M177 255H433" stroke="#a9a28c" stroke-width="5" stroke-linecap="round"/>
    <rect x="385" y="247" width="22" height="5" rx="2" fill="#ecdfc5"/>
    <path d="M36 65V209M21 80H51M21 112H51M21 144H51M21 176H51" stroke="#96acae" stroke-opacity=".24" stroke-width="2"/>
    <circle cx="489" cy="77" r="22" fill="none" stroke="#e2cfab" stroke-opacity=".4"/><path d="M489 61V77L500 84" stroke="#e2cfab" stroke-opacity=".65" stroke-width="2" fill="none"/>
    ${student(105, 175, { coat: '#b9c7b7' })}${student(478, 183, { flip: true, coat: '#d8bd8f', book: true })}
    <path d="M195 289H372M209 300H358" stroke="#b7baa4" stroke-opacity=".15"/>`;
}

function physicsScene(page) {
  const active = page > 0;
  const measured = page === 3;
  const formula = ['I = 0', 'I = U / R', '6 V / 3 Ω = 2 A', 'R = 6 Ω'][page];
  return `<rect width="560" height="340" fill="#30484b"/><path d="M0 281H560V340H0Z" fill="#263c40"/>
    <rect x="149" y="34" width="303" height="204" rx="7" fill="#253c40" stroke="#8b9c8e" stroke-width="2"/>
    <path d="M198 115V76H383V168H198V137" fill="none" stroke="#d9d4b4" stroke-width="2.5" stroke-linejoin="round"/>
    <path d="M186 115H210M190 137H206" stroke="#eee1be" stroke-width="3"/>
    <path d="M267 157H320V179H267Z" fill="#253c40" stroke="#eee1be" stroke-width="2"/>
    <path d="M382 106V140" stroke="#253c40" stroke-width="7"/><circle cx="383" cy="105" r="3.5" fill="#eee1be"/><circle cx="383" cy="140" r="3.5" fill="#eee1be"/><path d="M383 140L${active ? '383 105' : '401 111'}" stroke="#eee1be" stroke-width="2.5"/>
    <text x="292" y="128" font-family="Georgia, serif" font-size="${page === 2 ? '21' : '25'}" fill="#eee1be" text-anchor="middle">${formula}</text>
    ${measured ? `<circle cx="293" cy="76" r="18" fill="#253c40" stroke="#eee1be" stroke-width="2"/><text x="293" y="83" font-family="Georgia, serif" font-size="21" fill="#eee1be" text-anchor="middle">A</text><text x="327" y="62" font-family="Georgia, serif" font-size="18" fill="#e0c58e">1 A</text><path d="M241 168V209H346V168" fill="none" stroke="#d9d4b4" stroke-width="2"/><circle cx="293" cy="209" r="16" fill="#253c40" stroke="#eee1be" stroke-width="2"/><text x="293" y="216" font-family="Georgia, serif" font-size="21" fill="#eee1be" text-anchor="middle">V</text><text x="364" y="214" font-family="Georgia, serif" font-size="18" fill="#e0c58e">6 V</text><circle cx="241" cy="168" r="3" fill="#eee1be"/><circle cx="346" cy="168" r="3" fill="#eee1be"/>` : `<text x="292" y="210" font-family="Georgia, serif" font-size="${page === 2 ? '20' : '18'}" fill="#e0c58e" text-anchor="middle">${page === 2 ? '6 V / 6 Ω = 1 A' : page === 1 ? 'U [V] · R [Ω] · I [A]' : 'U · R · I'}</text>`}
    ${active ? '<g fill="#e0c58e"><circle cx="233" cy="76" r="3"/><circle cx="346" cy="76" r="3"/><circle cx="383" cy="157" r="3"/><circle cx="218" cy="168" r="3"/></g>' : ''}
    <path d="M170 274H401V285H170Z" fill="#a4a48e"/><path d="M185 285V327M388 285V327" stroke="#172e37" stroke-width="9"/>
    <path d="M231 246H344L354 272H221Z" fill="#7e9285" stroke="#bdc7ad" stroke-width="1.5"/><path d="M239 252H335L340 266H234Z" fill="#253c40"/><text x="287" y="263" font-family="Georgia, serif" font-size="12" fill="#eee1be" text-anchor="middle">${measured ? '6 V · 6 Ω · 1 A' : 'U · R · I'}</text>
    <path d="M36 75H102M36 111H102M36 147H102" stroke="#b5c2ab" stroke-opacity=".25" stroke-width="2"/><path d="M44 56V75H58V56M78 90V111H93V90" stroke="#d1c7a5" stroke-opacity=".35" stroke-width="7"/>
    ${student(113, 184, { coat: '#c7b48d', book: true })}${student(469, 177, { flip: true, coat: '#9cb7b0' })}`;
}

function historyScene(page) {
  const dates = ['07 · 1917', '12 · 1917', '12 · 1917', '1917'];
  return `<rect width="560" height="340" fill="#777b66"/><path d="M0 279H560V340H0Z" fill="#656d5b"/>
    <path d="M222 167V88A62 62 0 0 1 346 88V167Z" fill="#cfc8a8"/><path d="M229 160V88A55 55 0 0 1 339 88V160Z" fill="#a8b29b"/><path d="M284 33V164M227 94H342" stroke="#6f7a66" stroke-width="5"/>
    <path d="M232 146L265 112L293 137L318 114L340 146V159H232Z" fill="#8e9b85"/>
    <g fill="#4e6053"><rect x="27" y="55" width="122" height="180" rx="3"/><rect x="415" y="55" width="119" height="180" rx="3"/></g>
    <g stroke="#b9b794" stroke-width="3"><path d="M34 111H142M34 168H142M34 226H142M422 111H527M422 168H527M422 226H527"/></g>
    <g fill="#a6ab89"><path d="M42 70H55V107H42ZM64 66H73V107H64ZM80 76H96V107H80ZM105 70H119V107H105ZM43 127H61V164H43ZM69 122H79V164H69ZM91 129H104V164H91ZM112 123H130V164H112ZM427 67H440V107H427ZM448 75H466V107H448ZM474 67H484V107H474ZM493 70H509V107H493ZM429 123H447V164H429ZM455 130H468V164H455ZM477 122H492V164H477ZM500 128H518V164H500Z"/></g>
    <g fill="#c6b58b"><path d="M122 74H134V107H122ZM433 187H453V223H433ZM462 180H474V223H462ZM483 186H497V223H483ZM506 178H519V223H506Z"/></g>
    <rect x="169" y="160" width="224" height="108" rx="5" fill="#e5d7b4" transform="rotate(-3 280 214)"/>
    <path d="M197 224L209 212L221 218L232 207L247 208L254 195L269 202L289 196L300 204L319 201L326 210L347 206L354 219L363 224L354 234L336 234L326 243L307 240L294 247L279 240L265 242L250 234L236 241L222 232L205 237Z" fill="#b3b794" fill-opacity=".75" stroke="#87997b" stroke-width="1.2"/>
    <path d="M214 226Q263 204 289 221T349 214" stroke="#819986" stroke-width="2" fill="none" stroke-dasharray="4 4"/>
    <text x="282" y="181" font-size="19" font-family="Georgia, serif" fill="#5c654f" text-anchor="middle">${dates[Math.min(page, 3)]}</text>
    <circle cx="277" cy="216" r="4" fill="#9d7956"/><circle cx="331" cy="219" r="4" fill="#9d7956"/>
    <path d="M164 270H402V282H164Z" fill="#b7a57e"/><path d="M182 282V331M385 282V331" stroke="#465a4e" stroke-width="9"/>
    <path d="M195 262H236V269H195Z" fill="#6f816d"/><path d="M199 256H240V262H199Z" fill="#d1c2a0"/>
    <circle cx="360" cy="251" r="13" fill="none" stroke="#586f5d" stroke-width="4"/><path d="M350 261L338 274" stroke="#586f5d" stroke-width="5" stroke-linecap="round"/>
    ${student(108, 179, { coat: '#d0b88b', book: true })}${student(456, 182, { flip: true, coat: '#b5c2a3' })}`;
}

export function lessonArt(subject, page = 0) {
  const frame = Math.max(0, Math.min(3, Number(page) || 0));
  const scene = subject === 'history' ? historyScene(frame) : subject === 'physics' ? physicsScene(frame) : mathScene(frame);
  return `<svg class="lesson-illustration" viewBox="0 0 560 340" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false">${scene}</svg>`;
}
