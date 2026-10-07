if (typeof window === 'undefined') {
  // Emergency Bothost fallback: some deployments incorrectly use this browser bundle
  // as the Node entrypoint. In that case, hand control to the real Python bot.
  const { spawn } = require('node:child_process');
  const path = require('node:path');

  const mainPath = path.resolve(__dirname, '../../main.py');
  const child = spawn(process.env.PYTHON_BIN || 'python', [mainPath], {
    cwd: path.dirname(mainPath),
    env: process.env,
    stdio: 'inherit',
  });

  const forward = signal => {
    if (!child.killed) child.kill(signal);
  };
  process.on('SIGTERM', () => forward('SIGTERM'));
  process.on('SIGINT', () => forward('SIGINT'));

  child.on('error', error => {
    console.error('Failed to start Python bot:', error);
    process.exit(1);
  });
  child.on('exit', code => {
    process.exit(code ?? 1);
  });
} else {
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const tg = window.Telegram?.WebApp;
  const tgAtLeast = version => Boolean(tg && (!tg.isVersionAtLeast || tg.isVersionAtLeast(version)));
  const apiBase = (window.ANON_MGN_API_BASE || $('meta[name="api-base"]')?.content || '').replace(/\/$/, '');
  // Game icon metaphors follow the 24x24 / 2px Tabler Icons system.
  const hugeIconSvg = {
    "settings":"<path d=\"M21.3175 7.14139L20.8239 6.28479C20.4506 5.63696 20.264 5.31305 19.9464 5.18388C19.6288 5.05472 19.2696 5.15664 18.5513 5.36048L17.3311 5.70418C16.8725 5.80994 16.3913 5.74994 15.9726 5.53479L15.6357 5.34042C15.2766 5.11043 15.0004 4.77133 14.8475 4.37274L14.5136 3.37536C14.294 2.71534 14.1842 2.38533 13.9228 2.19657C13.6615 2.00781 13.3143 2.00781 12.6199 2.00781H11.5051C10.8108 2.00781 10.4636 2.00781 10.2022 2.19657C9.94085 2.38533 9.83106 2.71534 9.61149 3.37536L9.27753 4.37274C9.12465 4.77133 8.84845 5.11043 8.48937 5.34042L8.15249 5.53479C7.73374 5.74994 7.25259 5.80994 6.79398 5.70418L5.57375 5.36048C4.85541 5.15664 4.49625 5.05472 4.17867 5.18388C3.86109 5.31305 3.67445 5.63696 3.30115 6.28479L2.80757 7.14139C2.45766 7.74864 2.2827 8.05227 2.31666 8.37549C2.35061 8.69871 2.58483 8.95918 3.05326 9.48012L4.0843 10.6328C4.3363 10.9518 4.51521 11.5078 4.51521 12.0077C4.51521 12.5078 4.33636 13.0636 4.08433 13.3827L3.05326 14.5354C2.58483 15.0564 2.35062 15.3168 2.31666 15.6401C2.2827 15.9633 2.45766 16.2669 2.80757 16.8741L3.30114 17.7307C3.67443 18.3785 3.86109 18.7025 4.17867 18.8316C4.49625 18.9608 4.85542 18.8589 5.57377 18.655L6.79394 18.3113C7.25263 18.2055 7.73387 18.2656 8.15267 18.4808L8.4895 18.6752C8.84851 18.9052 9.12464 19.2442 9.2775 19.6428L9.61149 20.6403C9.83106 21.3003 9.94085 21.6303 10.2022 21.8191C10.4636 22.0078 10.8108 22.0078 11.5051 22.0078H12.6199C13.3143 22.0078 13.6615 22.0078 13.9228 21.8191C14.1842 21.6303 14.294 21.3003 14.5136 20.6403L14.8476 19.6428C15.0004 19.2442 15.2765 18.9052 15.6356 18.6752L15.9724 18.4808C16.3912 18.2656 16.8724 18.2055 17.3311 18.3113L18.5513 18.655C19.2696 18.8589 19.6288 18.9608 19.9464 18.8316C20.264 18.7025 20.4506 18.3785 20.8239 17.7307L21.3175 16.8741C21.6674 16.2669 21.8423 15.9633 21.8084 15.6401C21.7744 15.3168 21.5402 15.0564 21.0718 14.5354L20.0407 13.3827C19.7887 13.0636 19.6098 12.5078 19.6098 12.0077C19.6098 11.5078 19.7888 10.9518 20.0407 10.6328L21.0718 9.48012C21.5402 8.95918 21.7744 8.69871 21.8084 8.37549C21.8423 8.05227 21.6674 7.74864 21.3175 7.14139Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\"/>\n<path d=\"M15.5195 12C15.5195 13.933 13.9525 15.5 12.0195 15.5C10.0865 15.5 8.51953 13.933 8.51953 12C8.51953 10.067 10.0865 8.5 12.0195 8.5C13.9525 8.5 15.5195 10.067 15.5195 12Z\" stroke=\"currentColor\" stroke-width=\"1.5\"/>",
    "chevron-right":"<path d=\"M9.00005 6C9.00005 6 15 10.4189 15 12C15 13.5812 9 18 9 18\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "arrow-right":"<path d=\"M9.00005 6C9.00005 6 15 10.4189 15 12C15 13.5812 9 18 9 18\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "x":"<path d=\"M18 6L6.00081 17.9992M17.9992 18L6 6.00085\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "paperclip":"<path d=\"M5.82338 12L4.27922 10.4558C2.57359 8.75022 2.57359 5.98485 4.27922 4.27922C5.98485 2.57359 8.75022 2.57359 10.4558 4.27922L19.7208 13.5442C21.4264 15.2498 21.4264 18.0152 19.7208 19.7208C18.0152 21.4264 15.2498 21.4264 13.5442 19.7208L10.0698 16.2464C9.00379 15.1804 9.00379 13.4521 10.0698 12.386C11.1358 11.32 12.8642 11.32 13.9302 12.386L15.8604 14.3162\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "smile":"<circle cx=\"12\" cy=\"12\" r=\"10\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M8 15C8.91212 16.2144 10.3643 17 12 17C13.6357 17 15.0879 16.2144 16 15\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M15.625 8.387V8.91649M8.375 8.387V8.91649M8.75 8.75C8.75 8.33579 8.58211 8 8.375 8C8.16789 8 8 8.33579 8 8.75C8 9.16421 8.16789 9.5 8.375 9.5C8.58211 9.5 8.75 9.16421 8.75 8.75ZM16 8.75C16 8.33579 15.8321 8 15.625 8C15.4179 8 15.25 8.33579 15.25 8.75C15.25 9.16421 15.4179 9.5 15.625 9.5C15.8321 9.5 16 9.16421 16 8.75Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "mic":"<path d=\"M7 6.5C7 4.01472 9.01472 2 11.5 2C13.9853 2 16 4.01472 16 6.5V11.5C16 13.9853 13.9853 16 11.5 16C9.01472 16 7 13.9853 7 11.5V6.5Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M11.5 19H11.0828C7.57267 19 4.57706 16.4623 4 13M11.5 19H11.9172C15.4273 19 18.4229 16.4623 19 13M11.5 19V22\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "send":"<path d=\"M21.0477 3.05293C18.8697 0.707363 2.48648 6.4532 2.50001 8.551C2.51535 10.9299 8.89809 11.6617 10.6672 12.1581C11.7311 12.4565 12.016 12.7625 12.2613 13.8781C13.3723 18.9305 13.9301 21.4435 15.2014 21.4996C17.2278 21.5892 23.1733 5.342 21.0477 3.05293Z\" stroke=\"currentColor\" stroke-width=\"1.5\"/>\n<path d=\"M11.4999 12.5L14.9999 9\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "skip-forward":"<path d=\"M15.9351 12.6258C15.6807 13.8374 14.327 14.7077 11.6198 16.4481C8.67528 18.3411 7.20303 19.2876 6.01052 18.9229C5.60662 18.7994 5.23463 18.5823 4.92227 18.2876C4 17.4178 4 15.6118 4 12C4 8.38816 4 6.58224 4.92227 5.71235C5.23463 5.41773 5.60662 5.20057 6.01052 5.07707C7.20304 4.71243 8.67528 5.6589 11.6198 7.55186C14.327 9.29233 15.6807 10.1626 15.9351 11.3742C16.0216 11.7865 16.0216 12.2135 15.9351 12.6258Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linejoin=\"round\"/>\n<path d=\"M20 5V19\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\"/>",
    "square":"<path d=\"M4 12C4 8.72077 4 7.08116 4.81382 5.91891C5.1149 5.48891 5.48891 5.1149 5.91891 4.81382C7.08116 4 8.72077 4 12 4C15.2792 4 16.9188 4 18.0811 4.81382C18.5111 5.1149 18.8851 5.48891 19.1862 5.91891C20 7.08116 20 8.72077 20 12C20 15.2792 20 16.9188 19.1862 18.0811C18.8851 18.5111 18.5111 18.8851 18.0811 19.1862C16.9188 20 15.2792 20 12 20C8.72077 20 7.08116 20 5.91891 19.1862C5.48891 18.8851 5.1149 18.5111 4.81382 18.0811C4 16.9188 4 15.2792 4 12Z\" stroke=\"currentColor\" stroke-width=\"1.5\"/>",
    "crown":"<path d=\"M5 21H19\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M12.125 12.75H12M12.25 12.75C12.25 12.8881 12.1381 13 12 13C11.8619 13 11.75 12.8881 11.75 12.75C11.75 12.6119 11.8619 12.5 12 12.5C12.1381 12.5 12.25 12.6119 12.25 12.75Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M14.9152 7.61089L13.8078 5.38179C13.019 3.79393 12.6246 3 12 3C11.3754 3 10.981 3.79393 10.1922 5.38179L9.08483 7.61089C8.58107 8.62494 8.32919 9.13197 7.87976 9.24608C7.8485 9.25401 7.81689 9.26043 7.78503 9.26533C7.32682 9.3357 6.89919 8.96678 6.04393 8.22895C4.0124 6.47635 2.99663 5.60004 2.38034 5.94899C2.34045 5.97157 2.30213 5.99686 2.26565 6.02467C1.70197 6.45439 2.09541 7.74136 2.88229 10.3153L4.04783 14.1279C4.47098 15.5121 4.68255 16.2042 5.21787 16.6021C5.75318 17 6.47261 17 7.91147 17L16.0886 16.9999C17.5274 16.9999 18.2468 16.9999 18.7821 16.602C19.3175 16.2041 19.529 15.512 19.9522 14.1279L21.1177 10.3153C21.9046 7.74137 22.298 6.4544 21.7344 6.02468C21.6979 5.99687 21.6595 5.97158 21.6197 5.94899C21.0034 5.60006 19.9876 6.47636 17.9561 8.22896C17.1008 8.96679 16.6732 9.3357 16.215 9.26533C16.1831 9.26043 16.1515 9.25401 16.1202 9.24607C15.6708 9.13197 15.4189 8.62494 14.9152 7.61089Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "messages-circle":"<path d=\"M8.5 14.5H15.5M8.5 9.5H12\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M14.1706 20.8905C18.3536 20.6125 21.6856 17.2332 21.9598 12.9909C22.0134 12.1607 22.0134 11.3009 21.9598 10.4707C21.6856 6.22838 18.3536 2.84913 14.1706 2.57107C12.7435 2.47621 11.2536 2.47641 9.8294 2.57107C5.64639 2.84913 2.31441 6.22838 2.04024 10.4707C1.98659 11.3009 1.98659 12.1607 2.04024 12.9909C2.1401 14.536 2.82343 15.9666 3.62791 17.1746C4.09501 18.0203 3.78674 19.0758 3.30021 19.9978C2.94941 20.6626 2.77401 20.995 2.91484 21.2351C3.05568 21.4752 3.37026 21.4829 3.99943 21.4982C5.24367 21.5285 6.08268 21.1757 6.74868 20.6846C7.1264 20.4061 7.31527 20.2668 7.44544 20.2508C7.5756 20.2348 7.83177 20.3403 8.34401 20.5513C8.8044 20.7409 9.33896 20.8579 9.8294 20.8905C11.2536 20.9852 12.7435 20.9854 14.1706 20.8905Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linejoin=\"round\"/>",
    "message-circle":"<path d=\"M8.5 14.5H15.5M8.5 9.5H12\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M14.1706 20.8905C18.3536 20.6125 21.6856 17.2332 21.9598 12.9909C22.0134 12.1607 22.0134 11.3009 21.9598 10.4707C21.6856 6.22838 18.3536 2.84913 14.1706 2.57107C12.7435 2.47621 11.2536 2.47641 9.8294 2.57107C5.64639 2.84913 2.31441 6.22838 2.04024 10.4707C1.98659 11.3009 1.98659 12.1607 2.04024 12.9909C2.1401 14.536 2.82343 15.9666 3.62791 17.1746C4.09501 18.0203 3.78674 19.0758 3.30021 19.9978C2.94941 20.6626 2.77401 20.995 2.91484 21.2351C3.05568 21.4752 3.37026 21.4829 3.99943 21.4982C5.24367 21.5285 6.08268 21.1757 6.74868 20.6846C7.1264 20.4061 7.31527 20.2668 7.44544 20.2508C7.5756 20.2348 7.83177 20.3403 8.34401 20.5513C8.8044 20.7409 9.33896 20.8579 9.8294 20.8905C11.2536 20.9852 12.7435 20.9854 14.1706 20.8905Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linejoin=\"round\"/>",
    "messages-square":"<path d=\"M8.5 14.5H15.5M8.5 9.5H12\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M14.1706 20.8905C18.3536 20.6125 21.6856 17.2332 21.9598 12.9909C22.0134 12.1607 22.0134 11.3009 21.9598 10.4707C21.6856 6.22838 18.3536 2.84913 14.1706 2.57107C12.7435 2.47621 11.2536 2.47641 9.8294 2.57107C5.64639 2.84913 2.31441 6.22838 2.04024 10.4707C1.98659 11.3009 1.98659 12.1607 2.04024 12.9909C2.1401 14.536 2.82343 15.9666 3.62791 17.1746C4.09501 18.0203 3.78674 19.0758 3.30021 19.9978C2.94941 20.6626 2.77401 20.995 2.91484 21.2351C3.05568 21.4752 3.37026 21.4829 3.99943 21.4982C5.24367 21.5285 6.08268 21.1757 6.74868 20.6846C7.1264 20.4061 7.31527 20.2668 7.44544 20.2508C7.5756 20.2348 7.83177 20.3403 8.34401 20.5513C8.8044 20.7409 9.33896 20.8579 9.8294 20.8905C11.2536 20.9852 12.7435 20.9854 14.1706 20.8905Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linejoin=\"round\"/>",
    "search":"<path d=\"M17 17L21 21\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M19 11C19 6.58172 15.4183 3 11 3C6.58172 3 3 6.58172 3 11C3 15.4183 6.58172 19 11 19C15.4183 19 19 15.4183 19 11Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "chevron-left":"<g transform=\"translate(24 0) scale(-1 1)\"><path d=\"M9.00005 6C9.00005 6 15 10.4189 15 12C15 13.5812 9 18 9 18\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/></g>",
    "house":"<path d=\"M3 11.9896V14.5C3 17.7998 3 19.4497 4.02513 20.4749C5.05025 21.5 6.70017 21.5 10 21.5H14C17.2998 21.5 18.9497 21.5 19.9749 20.4749C21 19.4497 21 17.7998 21 14.5V11.9896C21 10.3083 21 9.46773 20.6441 8.74005C20.2882 8.01237 19.6247 7.49628 18.2976 6.46411L16.2976 4.90855C14.2331 3.30285 13.2009 2.5 12 2.5C10.7991 2.5 9.76689 3.30285 7.70242 4.90855L5.70241 6.46411C4.37533 7.49628 3.71179 8.01237 3.3559 8.74005C3 9.46773 3 10.3083 3 11.9896Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "gamepad-2":"<path d=\"M2.00825 15.8092C2.23114 12.3161 2.88737 9.7599 3.44345 8.27511C3.72419 7.5255 4.32818 6.96728 5.10145 6.78021C9.40147 5.73993 14.5986 5.73993 18.8986 6.78021C19.6719 6.96728 20.2759 7.5255 20.5566 8.27511C21.1127 9.7599 21.7689 12.3161 21.9918 15.8092C22.1251 17.8989 20.6148 19.0503 18.9429 19.8925C17.878 20.4289 17.0591 18.8457 16.5155 17.6203C16.2185 16.9508 15.5667 16.5356 14.8281 16.5356H9.17196C8.43331 16.5356 7.78158 16.9508 7.48456 17.6203C6.94089 18.8457 6.122 20.4289 5.05711 19.8925C3.40215 19.0588 1.87384 17.9157 2.00825 15.8092Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M5 4.5L6.96285 4M19 4.5L17 4\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M9 13L7.5 11.5M7.5 11.5L6 10M7.5 11.5L6 13M7.5 11.5L9 10\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\"/>\n<path d=\"M15.9881 10H15.9971\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M17.9881 13H17.9971\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "bell":"<path d=\"M19 18V9.5C19 5.63401 15.866 2.5 12 2.5C8.13401 2.5 5 5.63401 5 9.5V18\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M20.5 18H3.5\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M13.5 20C13.5 20.8284 12.8284 21.5 12 21.5M10.5 20C10.5 20.8284 11.1716 21.5 12 21.5M12 21.5V20\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linejoin=\"round\"/>",
    "user-round":"<path d=\"M20 21.0001C19.713 17.269 16.7289 14.3151 12.995 14.0662L12 13.9999C11.6446 14.0096 11.3134 14.0225 11.0008 14.0378C7.3 14.2192 4.28417 17.3057 4 21.0001\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<circle cx=\"12\" cy=\"6.99988\" r=\"4\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "target":"<path d=\"M15.1312 2.5C14.1462 2.17555 13.0936 2 12 2C6.47715 2 2 6.47715 2 12C2 17.5228 6.47715 22 12 22C17.5228 22 22 17.5228 22 12C22 10.9548 21.8396 9.94704 21.5422 9\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\"/>\n<path d=\"M17 12C17 14.7614 14.7614 17 12 17C9.23858 17 7 14.7614 7 12C7 9.23858 9.23858 7 12 7\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M19.5 4.5L12 12M19.5 4.5V2M19.5 4.5H22\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\"/>",
    "shield-check":"<path d=\"M18.7088 3.49534C16.8165 2.55382 14.5009 2 12 2C9.4991 2 7.1835 2.55382 5.29116 3.49534C4.36318 3.95706 3.89919 4.18792 3.4496 4.91378C3 5.63965 3 6.34248 3 7.74814V11.2371C3 16.9205 7.54236 20.0804 10.173 21.4338C10.9067 21.8113 11.2735 22 12 22C12.7265 22 13.0933 21.8113 13.8269 21.4338C16.4576 20.0804 21 16.9205 21 11.2371L21 7.74814C21 6.34249 21 5.63966 20.5504 4.91378C20.1008 4.18791 19.6368 3.95706 18.7088 3.49534Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M15 11C15 12.6568 13.6569 14 12 14C10.3431 14 9 12.6568 9 11C9 9.34314 10.3431 8 12 8C13.6569 8 15 9.34314 15 11Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "swords":"<path d=\"M2.5 19.5C2.98686 19.5717 3.45571 19.7949 3.83041 20.1696C4.20512 20.5443 4.42832 21.0131 4.5 21.5\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\"/>\n<path d=\"M8 16L4 20\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M9 16.5L19.8538 7.92675C20.1737 7.64942 20.3975 7.27769 20.4927 6.86509L21.5 2.5L17.1349 3.50733C16.7223 3.60254 16.3506 3.82626 16.0732 4.14625L7.5 15\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linejoin=\"round\"/>\n<path d=\"M4 13H4.57157C5.10201 13 5.61071 13.2107 5.98579 13.5858L10.4142 18.0142C10.7893 18.3893 11 18.898 11 19.4284V20\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "hash":"<path d=\"M14 21L18 3\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M6 21L10 3\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M5 8H21\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M3 16H19\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "pencil":"<path d=\"M14.0737 3.88545C14.8189 3.07808 15.1915 2.6744 15.5874 2.43893C16.5427 1.87076 17.7191 1.85309 18.6904 2.39232C19.0929 2.6158 19.4769 3.00812 20.245 3.79276C21.0131 4.5774 21.3972 4.96972 21.6159 5.38093C22.1438 6.37312 22.1265 7.57479 21.5703 8.5507C21.3398 8.95516 20.9446 9.33578 20.1543 10.097L10.7506 19.1543C9.25288 20.5969 8.504 21.3182 7.56806 21.6837C6.63212 22.0493 5.6032 22.0224 3.54536 21.9686L3.26538 21.9613C2.63891 21.9449 2.32567 21.9367 2.14359 21.73C1.9615 21.5234 1.98636 21.2043 2.03608 20.5662L2.06308 20.2197C2.20301 18.4235 2.27297 17.5255 2.62371 16.7182C2.97444 15.9109 3.57944 15.2555 4.78943 13.9445L14.0737 3.88545Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linejoin=\"round\"/>\n<path d=\"M13 4L20 11\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linejoin=\"round\"/>\n<path d=\"M14 22L22 22\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "thumbs-up":"<path d=\"M2 12.5C2 11.3954 2.89543 10.5 4 10.5C5.65685 10.5 7 11.8431 7 13.5V17.5C7 19.1569 5.65685 20.5 4 20.5C2.89543 20.5 2 19.6046 2 18.5V12.5Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M15.4787 7.80626L15.2124 8.66634C14.9942 9.37111 14.8851 9.72349 14.969 10.0018C15.0369 10.2269 15.1859 10.421 15.389 10.5487C15.64 10.7065 16.0197 10.7065 16.7791 10.7065H17.1831C19.7532 10.7065 21.0382 10.7065 21.6452 11.4673C21.7145 11.5542 21.7762 11.6467 21.8296 11.7437C22.2965 12.5921 21.7657 13.7351 20.704 16.0211C19.7297 18.1189 19.2425 19.1678 18.338 19.7852C18.2505 19.8449 18.1605 19.9013 18.0683 19.9541C17.116 20.5 15.9362 20.5 13.5764 20.5H13.0646C10.2057 20.5 8.77628 20.5 7.88814 19.6395C7 18.7789 7 17.3939 7 14.6239V13.6503C7 12.1946 7 11.4668 7.25834 10.8006C7.51668 10.1344 8.01135 9.58664 9.00069 8.49112L13.0921 3.96056C13.1947 3.84694 13.246 3.79012 13.2913 3.75075C13.7135 3.38328 14.3652 3.42464 14.7344 3.84235C14.774 3.8871 14.8172 3.94991 14.9036 4.07554C15.0388 4.27205 15.1064 4.37031 15.1654 4.46765C15.6928 5.33913 15.8524 6.37436 15.6108 7.35715C15.5838 7.46692 15.5488 7.5801 15.4787 7.80626Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "chart":"<path d=\"M7 17L7 13\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\"/>\n<path d=\"M12 17L12 7\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\"/>\n<path d=\"M17 17L17 11\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\"/>\n<path d=\"M2.5 12C2.5 7.52166 2.5 5.28249 3.89124 3.89124C5.28249 2.5 7.52166 2.5 12 2.5C16.4783 2.5 18.7175 2.5 20.1088 3.89124C21.5 5.28249 21.5 7.52166 21.5 12C21.5 16.4783 21.5 18.7175 20.1088 20.1088C18.7175 21.5 16.4783 21.5 12 21.5C7.52166 21.5 5.28249 21.5 3.89124 20.1088C2.5 18.7175 2.5 16.4783 2.5 12Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linejoin=\"round\"/>",
    "link":"<path d=\"M9.14339 10.691L9.35031 10.4841C11.329 8.50532 14.5372 8.50532 16.5159 10.4841C18.4947 12.4628 18.4947 15.671 16.5159 17.6497L13.6497 20.5159C11.671 22.4947 8.46279 22.4947 6.48405 20.5159C4.50532 18.5372 4.50532 15.329 6.48405 13.3503L6.9484 12.886\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\"/>\n<path d=\"M17.0516 11.114L17.5159 10.6497C19.4947 8.67095 19.4947 5.46279 17.5159 3.48405C15.5372 1.50532 12.329 1.50532 10.3503 3.48405L7.48405 6.35031C5.50532 8.32904 5.50532 11.5372 7.48405 13.5159C9.46279 15.4947 12.671 15.4947 14.6497 13.5159L14.8566 13.309\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\"/>",
    "sliders":"<path d=\"M3 7H6\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M3 17H9\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M18 17L21 17\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M15 7L21 7\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M6 7C6 6.06812 6 5.60218 6.15224 5.23463C6.35523 4.74458 6.74458 4.35523 7.23463 4.15224C7.60218 4 8.06812 4 9 4C9.93188 4 10.3978 4 10.7654 4.15224C11.2554 4.35523 11.6448 4.74458 11.8478 5.23463C12 5.60218 12 6.06812 12 7C12 7.93188 12 8.39782 11.8478 8.76537C11.6448 9.25542 11.2554 9.64477 10.7654 9.84776C10.3978 10 9.93188 10 9 10C8.06812 10 7.60218 10 7.23463 9.84776C6.74458 9.64477 6.35523 9.25542 6.15224 8.76537C6 8.39782 6 7.93188 6 7Z\" stroke=\"currentColor\" stroke-width=\"1.5\"/>\n<path d=\"M12 17C12 16.0681 12 15.6022 12.1522 15.2346C12.3552 14.7446 12.7446 14.3552 13.2346 14.1522C13.6022 14 14.0681 14 15 14C15.9319 14 16.3978 14 16.7654 14.1522C17.2554 14.3552 17.6448 14.7446 17.8478 15.2346C18 15.6022 18 16.0681 18 17C18 17.9319 18 18.3978 17.8478 18.7654C17.6448 19.2554 17.2554 19.6448 16.7654 19.8478C16.3978 20 15.9319 20 15 20C14.0681 20 13.6022 20 13.2346 19.8478C12.7446 19.6448 12.3552 19.2554 12.1522 18.7654C12 18.3978 12 17.9319 12 17Z\" stroke=\"currentColor\" stroke-width=\"1.5\"/>",
    "mail":"<path d=\"M2 6L8.91302 9.91697C11.4616 11.361 12.5384 11.361 15.087 9.91697L22 6\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linejoin=\"round\"/>\n<path d=\"M2.01577 13.4756C2.08114 16.5412 2.11383 18.0739 3.24496 19.2094C4.37608 20.3448 5.95033 20.3843 9.09883 20.4634C11.0393 20.5122 12.9607 20.5122 14.9012 20.4634C18.0497 20.3843 19.6239 20.3448 20.7551 19.2094C21.8862 18.0739 21.9189 16.5412 21.9842 13.4756C22.0053 12.4899 22.0053 11.5101 21.9842 10.5244C21.9189 7.45886 21.8862 5.92609 20.7551 4.79066C19.6239 3.65523 18.0497 3.61568 14.9012 3.53657C12.9607 3.48781 11.0393 3.48781 9.09882 3.53656C5.95033 3.61566 4.37608 3.65521 3.24495 4.79065C2.11382 5.92608 2.08114 7.45885 2.01576 10.5244C1.99474 11.5101 1.99475 12.4899 2.01577 13.4756Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linejoin=\"round\"/>",
    "circle-help":"<circle cx=\"12\" cy=\"12\" r=\"10\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M9.5 9.5C9.5 8.11929 10.6193 7 12 7C13.3807 7 14.5 8.11929 14.5 9.5C14.5 10.3569 14.0689 11.1131 13.4117 11.5636C12.7283 12.0319 12 12.6716 12 13.5\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M12.125 16.75H12M12.25 16.75C12.25 16.8881 12.1381 17 12 17C11.8619 17 11.75 16.8881 11.75 16.75C11.75 16.6119 11.8619 16.5 12 16.5C12.1381 16.5 12.25 16.6119 12.25 16.75Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "wifi-off":"<path d=\"M8.5 15.9996C9.36651 15.1331 10.4207 14.642 11.5 14.5264\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M5.5 12.5C8.67327 9.32673 12.6221 8.67087 16 10.5324\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M2 8.5C8.31579 3.16669 15.6842 3.16668 22 8.49989\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M21.0002 13.5L15.0002 19.5M21.0002 19.5L15.0002 13.5\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\"/>",
    "copy":"<path d=\"M7.5 14.5C7.5 11.2002 7.5 9.55025 8.52513 8.52513C9.55025 7.5 11.2002 7.5 14.5 7.5C17.7998 7.5 19.4497 7.5 20.4749 8.52513C21.5 9.55025 21.5 11.2002 21.5 14.5C21.5 17.7998 21.5 19.4497 20.4749 20.4749C19.4497 21.5 17.7998 21.5 14.5 21.5C11.2002 21.5 9.55025 21.5 8.52513 20.4749C7.5 19.4497 7.5 17.7998 7.5 14.5Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M7.5 16.5C6.10355 16.5 5.40533 16.5 4.84402 16.3036C3.83866 15.9518 3.0482 15.1613 2.69641 14.156C2.5 13.5947 2.5 12.8964 2.5 11.5V9.5C2.5 6.20017 2.5 4.55025 3.52513 3.52513C4.55025 2.5 6.20017 2.5 9.5 2.5H11.5C12.8964 2.5 13.5947 2.5 14.156 2.69641C15.1613 3.0482 15.9518 3.83866 16.3036 4.84402C16.5 5.40533 16.5 6.10355 16.5 7.5\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "gift":"<path d=\"M4 11V15C4 18.2998 4 19.9497 5.02513 20.9749C6.05025 22 7.70017 22 11 22H13C16.2998 22 17.9497 22 18.9749 20.9749C20 19.9497 20 18.2998 20 15V11\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M3 9C3 8.25231 3 7.87846 3.20096 7.6C3.33261 7.41758 3.52197 7.26609 3.75 7.16077C4.09808 7 4.56538 7 5.5 7H18.5C19.4346 7 19.9019 7 20.25 7.16077C20.478 7.26609 20.6674 7.41758 20.799 7.6C21 7.87846 21 8.25231 21 9C21 9.74769 21 10.1215 20.799 10.4C20.6674 10.5824 20.478 10.7339 20.25 10.8392C19.9019 11 19.4346 11 18.5 11H5.5C4.56538 11 4.09808 11 3.75 10.8392C3.52197 10.7339 3.33261 10.5824 3.20096 10.4C3 10.1215 3 9.74769 3 9Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linejoin=\"round\"/>\n<path d=\"M6 3.78571C6 2.79949 6.79949 2 7.78571 2H8.14286C10.2731 2 12 3.7269 12 5.85714V7H9.21429C7.43908 7 6 5.56091 6 3.78571Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linejoin=\"round\"/>\n<path d=\"M18 3.78571C18 2.79949 17.2005 2 16.2143 2H15.8571C13.7269 2 12 3.7269 12 5.85714V7H14.7857C16.5609 7 18 5.56091 18 3.78571Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linejoin=\"round\"/>\n<path d=\"M12 11L12 22\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>",
    "trophy":"<path d=\"M5 21H19\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M12.125 12.75H12M12.25 12.75C12.25 12.8881 12.1381 13 12 13C11.8619 13 11.75 12.8881 11.75 12.75C11.75 12.6119 11.8619 12.5 12 12.5C12.1381 12.5 12.25 12.6119 12.25 12.75Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n<path d=\"M14.9152 7.61089L13.8078 5.38179C13.019 3.79393 12.6246 3 12 3C11.3754 3 10.981 3.79393 10.1922 5.38179L9.08483 7.61089C8.58107 8.62494 8.32919 9.13197 7.87976 9.24608C7.8485 9.25401 7.81689 9.26043 7.78503 9.26533C7.32682 9.3357 6.89919 8.96678 6.04393 8.22895C4.0124 6.47635 2.99663 5.60004 2.38034 5.94899C2.34045 5.97157 2.30213 5.99686 2.26565 6.02467C1.70197 6.45439 2.09541 7.74136 2.88229 10.3153L4.04783 14.1279C4.47098 15.5121 4.68255 16.2042 5.21787 16.6021C5.75318 17 6.47261 17 7.91147 17L16.0886 16.9999C17.5274 16.9999 18.2468 16.9999 18.7821 16.602C19.3175 16.2041 19.529 15.512 19.9522 14.1279L21.1177 10.3153C21.9046 7.74137 22.298 6.4544 21.7344 6.02468C21.6979 5.99687 21.6595 5.97158 21.6197 5.94899C21.0034 5.60006 19.9876 6.47636 17.9561 8.22896C17.1008 8.96679 16.6732 9.3357 16.215 9.26533C16.1831 9.26043 16.1515 9.25401 16.1202 9.24607C15.6708 9.13197 15.4189 8.62494 14.9152 7.61089Z\" stroke=\"currentColor\" stroke-width=\"1.5\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>"
  };
  const state = {page:'home', modal:null, status:'free', position:null, user:{nick:'Аноним',rank:'👤 Вася',stars:0,age:0,district:'',gender:'',looking_for:'',photo_url:'',theme:'pink'},stats:{online:0,chatting:0,searching:0,dialogs:0,messages:0,ratings:0,games:0,battle_games:0,number_games:0,streak:0,best_streak:0,quest_current:0,quest_target:20},referral:{invited:0,earned:0},referral_url:'',bot_url:'',events:[],subscription:null};
  let statusRequestSeq = 0;
  let statusAppliedSeq = 0;
  let statusTimer = null;
  let searchBusy = false;
  let topPeriod = 'week';
  let sbpPollTimer = null;
  let topRequestSeq = 0;
  let realtime = null;
  let realtimeConnected = false;
  let resultShownFor = 0;
  const chat = {latest:0,startedAt:0,sent:0,received:0,timer:null,geoTimer:null,seen:new Set(),stickersLoaded:false,recording:false,recorder:null,stream:null,chunks:[],recordTimer:null,mediaCache:new Map(),game:null,gameHoldUntil:0,reply:null};
  const CHAT_EMOJIS = ['😀','😃','😄','😁','😂','🤣','🥹','😊','🙂','😉','😍','😘','😎','🤨','😐','😴','😭','😡','🤬','🥰','🤍','❤️','🩷','🔥','⭐','✨','💀','🤝','👍','👎','🙏','💬','👀','🤡','😈','💯','🎉','🥳','😏','🙃','😌','🤔','😳','🫠','😅','🤝','💋','🫶'];
  const svg = n => `<svg viewBox="0 0 24 24" aria-hidden="true">${hugeIconSvg[n] || hugeIconSvg['message-circle']}</svg>`;
  function icons(root=document){$$('[data-icon]',root).forEach(el=>{el.innerHTML=svg(el.dataset.icon)})}
  function esc(v=''){return String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
  function haptic(type='light'){try{if(tgAtLeast('6.1'))tg.HapticFeedback?.impactOccurred(type)}catch(_){}}
  function notify(type='success'){try{if(tgAtLeast('6.1'))tg.HapticFeedback?.notificationOccurred(type)}catch(_){}}
  function toast(message){const el=$('#toast');el.textContent=message;el.classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.classList.remove('show'),2400)}
  async function request(path, options={}){
    const headers={'Content-Type':'application/json',...(options.headers||{})}; if(tg?.initData)headers['X-Telegram-Init-Data']=tg.initData;
    const controller=new AbortController();
    const timeout=setTimeout(()=>controller.abort(),5000);
    let res;
    try{res=await fetch(apiBase+path,{cache:'no-store',...options,headers,signal:controller.signal})}
    catch(e){if(e?.name==='AbortError')throw new Error('Сервер не ответил за 5 секунд');throw new Error('Нет соединения с сервером')}
    finally{clearTimeout(timeout)}
    let data={}; try{data=await res.json()}catch(_){}
    if(!res.ok){
      if(res.status===401)throw new Error('Сессия Telegram устарела. Закрой и снова открой Mini App');
      throw new Error(data.message||`Ошибка ${res.status}`);
    }
    return data;
  }
  async function safe(path,options,fallback=null){try{return await request(path,options)}catch(e){if(tg?.initData)toast(e.message);return fallback}}
  async function upload(path, formData){
    const headers={}; if(tg?.initData)headers['X-Telegram-Init-Data']=tg.initData;
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),35000);
    let res;
    try{res=await fetch(apiBase+path,{method:'POST',body:formData,headers,cache:'no-store',signal:controller.signal})}
    catch(e){if(e?.name==='AbortError')throw new Error('Загрузка заняла слишком долго');throw new Error('Нет соединения с сервером')}
    finally{clearTimeout(timeout)}
    let data={};try{data=await res.json()}catch(_){}
    if(!res.ok)throw new Error(data.message||`Ошибка ${res.status}`);
    return data;
  }
  async function mediaBlobUrl(url){
    if(!url)return '';
    if(chat.mediaCache.has(url))return chat.mediaCache.get(url);
    const headers={};if(tg?.initData)headers['X-Telegram-Init-Data']=tg.initData;
    const res=await fetch(apiBase+url,{headers,cache:'no-store'});
    if(!res.ok)throw new Error('Медиа недоступно');
    const blob=await res.blob();
    const objectUrl=URL.createObjectURL(blob);
    if(chat.mediaCache.size>=80){
      const first=chat.mediaCache.entries().next().value;
      if(first){URL.revokeObjectURL(first[1]);chat.mediaCache.delete(first[0])}
    }
    chat.mediaCache.set(url,objectUrl);
    return objectUrl;
  }
  function normalizeStatus(value){return value==='paired'?'paired':value==='queued'?'queued':'free'}
  function applyStatusSnapshot(data, seq=0){
    if(!data)return false;
    if(seq && seq<statusAppliedSeq)return false;
    if(seq)statusAppliedSeq=seq;
    const previous=state.status;
    state.status=normalizeStatus(data.status);
    state.position=state.status==='queued'?(data.position||null):null;
    if(data.stats)state.stats={...state.stats,...data.stats};
    render();
    if(state.status==='paired' && previous!=='paired' && state.page==='search')go('chat');
    if(state.status!=='paired' && state.page==='chat')go(state.status==='queued'?'search':'home');
    return true;
  }
  async function syncStatus(silent=true){
    if(!tg?.initData)return false;
    const seq=++statusRequestSeq;
    try{
      const data=await request(`/api/miniapp/status?_=${Date.now()}`);
      return applyStatusSnapshot(data,seq);
    }catch(e){
      if(!silent)toast(e.message);
      return false;
    }
  }
  function startStatusSync(){
    if(statusTimer||!tg?.initData)return;
    statusTimer=setInterval(()=>{if(!document.hidden&&!realtimeConnected)syncStatus(true)},15000);
  }
  async function handleRealtimeEvent(event={}){
    const type=event.type||'';
    if(type==='ready'){
      realtimeConnected=true;
      await syncStatus(true);
      if(state.status==='paired')await syncChat(true);
      return;
    }
    if(type==='chat_changed'){
      if(state.status!=='paired')await syncStatus(true);
      if(state.status==='paired')await syncChat(false);
      return;
    }
    if(type==='status_changed'){
      const wasPaired=state.status==='paired';
      await syncStatus(true);
      if(state.status==='paired')await syncChat(true);
      else if(wasPaired)await loadDialogResult(true);
      return;
    }
    if(type==='events_changed'){
      await loadNotifications();
      return;
    }
    if(type==='poll_changed'){
      await loadHomePoll();
      return;
    }
    if(type==='result_changed'){
      await loadDialogResult(false);
    }
  }
  function startRealtime(){
    if(!tg?.initData||!window.AnonRealtime||realtime)return;
    realtime=new window.AnonRealtime({
      baseUrl:apiBase,
      initData:tg.initData,
      onState:connected=>{
        realtimeConnected=Boolean(connected);
        if(!connected&&!document.hidden){syncStatus(true);if(state.status==='paired')syncChat(false)}
      },
      onEvent:event=>{handleRealtimeEvent(event).catch(()=>{})}
    });
    realtime.start();
  }
  function demo(){Object.assign(state.user,{nick:'Аноним-4821',rank:'Завсегдатай',stars:1250,age:17,district:'Правый берег',gender:'m',looking_for:'f'});Object.assign(state.stats,{online:34,chatting:22,searching:12,dialogs:682,messages:8884,ratings:128,games:43,battle_games:31,number_games:12,streak:7,best_streak:23,quest_current:14});state.referral={invited:8,earned:400};state.referral_url='https://t.me/AnonChatMgn_Bot?start=ref_demo';state.bot_url='https://t.me/AnonChatMgn_Bot';state.subscription={claimed:false,amount:100,url:'https://t.me/anonmgn'};state.events=[{id:'demo1',type:'personal',icon:'message-circle',title:'Диалог активен',text:'Собеседник найден. Возвращайся в чат.',time:'сейчас',unread:true},{id:'demo2',type:'games',icon:'gamepad-2',title:'Новая игра',text:'Можно пригласить собеседника в Битву мнений или Числа.',time:'сегодня',unread:false}]}
  function setAll(key,value){$$(`[data-${key}]`).forEach(el=>el.textContent=value)}
  function applyTheme(){const theme=state.user.theme||localStorage.getItem('anon_mgn_theme')||'pink';state.user.theme=theme;document.body.dataset.theme=theme}
  function render(){
    setAll('nick',state.user.nick);setAll('rank',state.user.rank);setAll('stars',state.user.stars);
    setAll('online',state.stats.online);setAll('chatting',state.stats.chatting);setAll('searching',state.stats.searching);
    setAll('dialogs',state.stats.dialogs);setAll('messages',state.stats.messages);setAll('ratings',state.stats.ratings);setAll('games',state.stats.games);
    setAll('battle-games',state.stats.battle_games);setAll('number-games',state.stats.number_games);setAll('streak',state.stats.streak);
    setAll('invited',state.referral.invited);setAll('ref-earned',state.referral.earned);
    setAll('quest-progress-text',`${state.stats.quest_current}/${state.stats.quest_target}`);
    $$('[data-quest-progress]').forEach(el=>el.style.width=`${Math.min(100,state.stats.quest_current/Math.max(1,state.stats.quest_target)*100)}%`);
    const initial=(state.user.nick||'А').replace(/^./u,m=>m.toUpperCase()).slice(0,1);
    $$('[data-avatar-fallback]').forEach(el=>el.textContent=initial);
    $$('[data-avatar]').forEach(el=>{if(state.user.photo_url){el.src=state.user.photo_url;el.hidden=false}else{el.removeAttribute('src');el.hidden=true}});
    $$('[data-flame]').forEach((el,i)=>el.classList.toggle('on',i<Math.min(7,state.stats.streak)));
    $$('[data-setting]').forEach(group=>$$('button',group).forEach(b=>b.classList.toggle('active',String(b.dataset.value)===String(state.user[group.dataset.setting]||''))));
    applyTheme();renderSearch();renderEvents();
  }
  function renderSearch(){
    const card=$('.search-card'),title=$('#searchTitle'),text=$('#searchText'),button=$('#searchToggle');
    const heroTitle=$('.hero h1'),heroText=$('.hero p'),heroButton=$('.hero .primary');
    card.classList.toggle('searching',state.status==='queued');
    button.disabled=searchBusy;
    if(state.status==='paired'){
      title.textContent='Чат активен';
      text.textContent='Собеседник найден. Можно общаться прямо здесь.';
      button.innerHTML=`Открыть чат ${svg('arrow-right')}`;
      button.dataset.action='chat';
      if(heroTitle)heroTitle.textContent='Чат активен';
      if(heroText)heroText.textContent='Собеседник найден. Продолжай общение в Mini App.';
      if(heroButton){heroButton.innerHTML=`Открыть чат ${svg('arrow-right')}`;heroButton.dataset.nav='chat'}
      const nav=$('#searchNav');if(nav)nav.dataset.nav='chat'
    }else if(state.status==='queued'){
      const nav=$('#searchNav');if(nav)nav.dataset.nav='search'
      if(heroButton)heroButton.dataset.nav='search';
      title.textContent='Идёт поиск';
      text.textContent=state.position?`Твоя позиция в очереди: ${state.position}`:'Ищем собеседника. Можно закрыть Mini App.';
      button.textContent='Остановить поиск';
      button.dataset.action='stop';
      if(heroTitle)heroTitle.textContent='Идёт поиск';
      if(heroText)heroText.textContent='Поиск продолжается в фоне.';
      if(heroButton)heroButton.textContent='Остановить поиск';
    }else{
      const nav=$('#searchNav');if(nav)nav.dataset.nav='search'
      if(heroButton)heroButton.dataset.nav='search';
      title.textContent='Найти собеседника';
      text.textContent='Настрой предпочтения и начни поиск.';
      button.innerHTML=`Найти собеседника ${svg('arrow-right')}`;
      button.dataset.action='start';
      if(heroTitle)heroTitle.textContent='Найти собеседника';
      if(heroText)heroText.textContent='Подберём человека для разговора.';
      if(heroButton)heroButton.innerHTML=`Найти собеседника ${svg('arrow-right')}`;
    }
  }
  function eventTime(ts){
    const value=Number(ts||0)*1000;if(!value)return '';
    const diff=Math.max(0,Date.now()-value);
    if(diff<60000)return 'сейчас';
    if(diff<3600000)return `${Math.max(1,Math.floor(diff/60000))} мин назад`;
    if(diff<86400000)return `${Math.max(1,Math.floor(diff/3600000))} ч назад`;
    return new Date(value).toLocaleDateString('ru-RU',{day:'2-digit',month:'short'});
  }
  function eventMatchesFilter(item,filter){
    if(filter==='all')return true;
    if(filter==='games')return item.type==='games';
    if(filter==='rewards')return ['achievement','quest','rating'].includes(item.type);
    if(filter==='personal')return !['games','achievement','quest','rating'].includes(item.type);
    return item.type===filter;
  }
  function renderEvents(filter='all'){
    const list=$('#eventList');if(!list)return;
    const items=state.events.filter(x=>eventMatchesFilter(x,filter));
    list.innerHTML=items.length?items.map(x=>`<button class="event ${x.unread?'unread':''}" data-event-id="${x.id}" data-event-action="${esc(x.action||'')}"><span>${svg(x.icon||'bell')}</span><div><strong>${esc(x.title)}</strong><p>${esc(x.text)}</p><small>${eventTime(x.created_at)}</small></div>${x.action?svg('chevron-right'):''}</button>`).join(''):'<div class="empty">Здесь пока тихо.</div>';
    const unread=state.events.some(x=>x.unread);$$('[data-event-dot]').forEach(el=>el.hidden=!unread);
    $$('[data-event-id]',list).forEach(el=>el.onclick=()=>openEvent(el.dataset.eventId,el.dataset.eventAction));
  }
  async function loadNotifications(markRead=false){
    const data=await safe('/api/miniapp/notifications',{},null);
    if(!data)return;
    state.events=data.items||[];
    renderEvents($('#eventFilter .active')?.dataset.filter||'all');
    if(markRead&&data.unread){
      await safe('/api/miniapp/notifications/all/read',{method:'POST',body:'{}'},null);
      state.events=state.events.map(x=>({...x,unread:false}));
      renderEvents($('#eventFilter .active')?.dataset.filter||'all');
    }
  }
  async function openEvent(id,action){
    if(/^\d+$/.test(String(id||'')))await safe(`/api/miniapp/notifications/${id}/read`,{method:'POST',body:'{}'},null);
    if(action==='chat')go('chat');
    else if(action==='search')go('search');
    else if(action==='profile')go('profile');
    else if(action==='profile:achievements')openModal('achievements','Достижения');
    else if(action==='profile:quests')openModal('quests','Цели дня');
    else if(action==='dialog:result')await loadDialogResult(true);
    else if(action==='events')go('events');
    await loadNotifications(false);
  }
  function topFallback(period){
    if(tg?.initData)return [];
    const base=[
      {place:1,nick:'Аноним-4821',rank:'🏆 Легенда',stars:period==='week'?620:period==='month'?2140:6840,me:true},
      {place:2,nick:'northwind',rank:'⭐ Свой',stars:period==='week'?540:period==='month'?1960:5910},
      {place:3,nick:'Аноним-1520',rank:'💬 Чел',stars:period==='week'?490:period==='month'?1720:4870},
      {place:4,nick:'mgn_user',rank:'🤝 Бро',stars:period==='week'?410:period==='month'?1510:3990}
    ];
    return base;
  }
  function renderTopPage(items=[]){
    const root=$('#topPageList');if(!root)return;
    if(!items.length){root.innerHTML='<div class="empty top-empty">За этот период пока никто не набрал ⭐.</div>';return}
    root.innerHTML=items.map(x=>{
      const medal=x.place===1?'🥇':x.place===2?'🥈':x.place===3?'🥉':'';
      return `<article class="top-page-item ${x.me?'me':''} ${x.place<=3?'podium':''}">
        <span class="top-place">${medal||x.place}</span>
        <span class="top-person"><strong>${esc(x.nick)}${x.emoji?` <i class="top-user-emoji">${esc(x.emoji)}</i>`:''}</strong><small>${esc(x.rank||'')}</small></span>
        <span class="top-stars"><b>${Number(x.stars||0).toLocaleString('ru-RU')}</b><i>★</i></span>
      </article>`;
    }).join('');
  }
  async function loadTopPage(period=topPeriod){
    topPeriod=['week','month','all'].includes(period)?period:'week';
    $$('#topPeriods button').forEach(b=>b.classList.toggle('active',b.dataset.topPeriod===topPeriod));
    const root=$('#topPageList');if(root)root.innerHTML='<div class="loading"><i class="spinner"></i>Загрузка…</div>';
    const seq=++topRequestSeq;
    const data=await safe(`/api/miniapp/top?period=${topPeriod}&_=${Date.now()}`,{},null);
    if(seq!==topRequestSeq)return;
    const items=data?.items||topFallback(topPeriod);
    renderTopPage(items);
    const nft=$('#nftLeader');
    if(nft){
      const leader=items[0];
      if(topPeriod==='week'&&leader){
        nft.hidden=false;
        nft.innerHTML=`<small>РОЗЫГРЫШ NFT</small><strong>Сейчас выигрывает: ${esc(leader.nick)}</strong><span>Конец розыгрыша · 11 октября 2026 в 20:00</span>`;
      }else nft.hidden=true;
    }
    const mine=$('#topMe');
    if(mine&&data?.my){
      const until=data.ends_at?new Date(data.ends_at*1000).toLocaleDateString('ru-RU',{day:'numeric',month:'long'}):'';
      mine.hidden=false;
      mine.innerHTML=`<span><small>ТВОЁ МЕСТО</small><strong>#${data.my.place||'—'}</strong></span><span><b>${Number(data.my.stars||0).toLocaleString('ru-RU')} ★</b><small>${data.my.place>10&&data.my.to_top10?`${data.my.to_top10} ★ до топ-10`:'Ты в топ-10'}${until?` · до ${until}`:''}</small></span>`;
    }else if(mine)mine.hidden=true;
  }

  async function load(){
    if(!tg?.initData){demo();render();return}
    const seq=++statusRequestSeq;
    const data=await safe(`/api/miniapp/me?_=${Date.now()}`,{},null);
    if(data){
      state.user={...state.user,...data.user};state.stats={...state.stats,...data.stats};
      state.referral=data.referral||state.referral;state.referral_url=data.referral_url||'';state.bot_url=data.bot_url||'';
      state.events=data.notifications||[];applyStatusSnapshot(data,seq);
      await Promise.all([loadHomePoll(),loadHomeQuest()]);
      return;
    }
    render();
  }
  function go(page){
    if(page==='chat' && state.status!=='paired')page=state.status==='queued'?'search':'home';
    state.page=page;
    document.body.classList.toggle('chat-open',page==='chat');
    $$('.page').forEach(p=>p.classList.toggle('active',p.dataset.page===page));
    $$('#bottomNav button').forEach(b=>b.classList.toggle('active',b.dataset.nav===page));
    window.scrollTo({top:0,behavior:'auto'});
    haptic();
    if(page==='search')syncStatus(true);
    if(page==='top')loadTopPage(topPeriod);
    if(page==='events')loadNotifications(true);
    if(page==='home'){loadHomePoll();loadHomeQuest()}
    if(page==='chat'){syncChat(true);startChatSync()}else stopChatSync();
    try{if(tgAtLeast('6.1'))page==='home'?tg.BackButton.hide():tg.BackButton.show()}catch(_){}
  }
  function openModal(kind,title,eyebrow='АНОН МГН'){$('#modalTitle').textContent=title;$('#modalEyebrow').textContent=eyebrow;$('#modalBody').innerHTML='<div class="loading"><i class="spinner"></i>Загрузка…</div>';$('#modal').hidden=false;document.body.style.overflow='hidden';state.modal=kind;try{if(tgAtLeast('6.1'))tg.BackButton.show()}catch(_){};haptic();renderModal(kind)}
  function closeModal(){$('#modal').hidden=true;document.body.style.overflow='';state.modal=null;try{if(tgAtLeast('6.1'))state.page==='home'?tg.BackButton.hide():tg.BackButton.show()}catch(_){}}
  function panel(title,text){return `<section class="panel"><h3>${title}</h3><p>${text}</p></section>`}
  async function loadHomeQuest(){
    const data=await safe('/api/miniapp/quests',{},null);const first=data?.items?.[0];if(!first)return;
    state.stats.quest_current=Number(first.current||0);state.stats.quest_target=Number(first.target||1);
    const label=$('[data-quest-label]');if(label)label.textContent=`${first.title} · ${first.reward||0} ★`;
    setAll('quest-progress-text',first.claimed?'Готово':`${first.current}/${first.target}`);
    $$('[data-quest-progress]').forEach(el=>el.style.width=`${Math.min(100,first.current/Math.max(1,first.target)*100)}%`);
  }
  function renderHomePoll(poll){
    const root=$('#homePoll');if(!root)return;
    if(!poll){root.hidden=true;root.innerHTML='';return}
    root.hidden=false;
    const voted=poll.selected===0||poll.selected===1;
    root.innerHTML=`<header><span><small>ОПРОС ДНЯ</small><strong>Что выбрал город</strong></span><b>${poll.total||0} голосов</b></header>
      <h3>${esc(poll.question)}</h3>
      <div class="poll-options">
        ${poll.options.map((label,i)=>`<button type="button" data-poll-choice="${i}" class="${poll.selected===i?'selected':''}">
          <span><strong>${esc(label)}</strong>${voted?`<small>${poll.percentages?.[i]||0}%</small>`:''}</span>
          ${voted?`<i style="width:${poll.percentages?.[i]||0}%"></i>`:''}
        </button>`).join('')}
      </div>`;
    $$('[data-poll-choice]',root).forEach(btn=>btn.onclick=async()=>{
      const choice=+btn.dataset.pollChoice;
      const data=await safe('/api/miniapp/poll/vote',{method:'POST',body:JSON.stringify({poll_id:poll.id,choice})},null);
      if(data?.poll){renderHomePoll(data.poll);haptic();notify()}
    });
  }
  async function loadHomePoll(){
    if(!tg?.initData)return;
    const data=await safe('/api/miniapp/poll',{},null);
    if(data)renderHomePoll(data.poll||null);
  }
  function formatDuration(seconds){
    seconds=Math.max(0,Number(seconds||0));
    if(seconds<60)return 'меньше минуты';
    const mins=Math.floor(seconds/60);return mins<60?`${mins} мин`:`${Math.floor(mins/60)} ч ${mins%60} мин`;
  }
  function resultGames(games=[]){
    if(!games?.length)return '';
    return `<div class="result-games">${games.map(g=>{
      if(g.type==='battle')return `<span>⚔️ Битва мнений <b>${g.matches||0}/${g.total||0}</b></span>`;
      if(g.type==='numbers')return `<span>🔢 Числа <b>${g.exact||0} точных</b></span>`;
      if(g.type==='geo')return `<span>GeoGuessr📍 <b>${g.total||g.games||1} раунд.</b></span>`;
      return `<span>🗣 Объясни слово <b>${g.games||1}</b></span>`;
    }).join('')}</div>`;
  }
  function showDialogResult(result){
    if(!result||!result.match_id)return;
    resultShownFor=Number(result.match_id);
    if(state.modal!=='dialog-result'){openModal('dialog-result','Итог разговора','ДИАЛОГ ЗАВЕРШЁН');return}
    const body=$('#modalBody');
    body.innerHTML=`<section class="dialog-result-card">
      <div class="result-duration"><small>Диалог длился</small><strong>${formatDuration(result.duration)}</strong></div>
      <div class="result-grid">
        <div><small>Отправлено</small><strong>${result.sent||0}</strong></div>
        <div><small>Получено</small><strong>${result.received||0}</strong></div>
        <div class="stars"><small>Заработано</small><strong>+${result.earned||0} ★</strong></div>
      </div>
      ${resultGames(result.games)}
    </section>
    ${result.rated?'<div class="rated-done">✓ Оценка уже учтена</div>':`<section class="rate-block"><small>Как прошёл разговор?</small><div><button data-rate="1">👍 Норм</button><button data-rate="0">👎 Не зашло</button></div></section>`}
    <div class="modal-actions one"><button class="action accent" id="resultNext">Найти собеседника</button></div>`;
    $$('[data-rate]',body).forEach(btn=>btn.onclick=()=>rateDialog(btn.dataset.rate==='1',body));
    $('#resultNext').onclick=async()=>{closeModal();if(state.status==='free'){go('search')}else go(state.status==='paired'?'chat':'search')};
  }
  async function loadDialogResult(autoShow=false){
    if(!tg?.initData)return null;
    const data=await safe('/api/miniapp/chat/result',{},null),result=data?.result||null;
    if(autoShow&&result&&!result.rated&&Number(result.match_id)!==resultShownFor)showDialogResult(result);
    return result;
  }
  async function rateDialog(positive,body){
    $$('[data-rate]',body).forEach(b=>b.disabled=true);
    const data=await safe('/api/miniapp/chat/rate',{method:'POST',body:JSON.stringify({positive})},null);
    if(!data){$$('[data-rate]',body).forEach(b=>b.disabled=false);return}
    const block=$('.rate-block',body);if(block)block.outerHTML='<div class="rated-done">✓ Спасибо, оценка учтена</div>';
    toast(positive?'Оценка отправлена':'Записал');notify();
    await loadNotifications(false);
  }
  function openReport(){
    if(state.status!=='paired')return toast('Сейчас нет активного собеседника');
    openModal('report','Пожаловаться','БЕЗОПАСНОСТЬ');
  }
  async function submitReport(){
    const reason=$('[name="reportReason"]:checked')?.value||'';
    const comment=$('#reportComment')?.value.trim()||'';
    if(!reason)return toast('Выбери причину');
    const data=await safe('/api/miniapp/chat/report',{method:'POST',body:JSON.stringify({reason,comment})},null);
    if(data){closeModal();toast('Жалоба отправлена');notify();await loadNotifications(false);await syncStatus(true)}
  }
  async function renderModal(kind){const body=$('#modalBody');
    if(kind==='dialog-result'){const data=await safe('/api/miniapp/chat/result',{},null);if(data?.result)showDialogResult(data.result);else body.innerHTML='<div class="empty">Итог уже недоступен.</div>';return}
    if(kind==='report'){
      const reasons=[['spam','Спам / реклама'],['insult','Оскорбления'],['sexual','Неподходящий контент'],['threat','Угрозы'],['personal','Личные данные'],['other','Другое']];
      body.innerHTML=`${panel('Что случилось?','Жалоба сохранит только небольшой контекст последних сообщений этого диалога для модерации.')}<div class="report-reasons">${reasons.map(([v,t])=>`<label><input type="radio" name="reportReason" value="${v}"><span>${t}</span></label>`).join('')}</div><div class="form-field"><label>Комментарий · необязательно</label><textarea id="reportComment" maxlength="500" placeholder="Коротко опиши проблему"></textarea></div><div class="modal-actions one"><button class="action danger" id="sendReport">Отправить жалобу</button></div>`;
      $('#sendReport').onclick=submitReport;return;
    }
    if(kind==='achievements'){
      const data=await safe('/api/miniapp/achievements',{},null);const items=data?.items||[];
      body.innerHTML=`<div class="achievement-head"><strong>${data?.unlocked||0}/${data?.total||items.length}</strong><span>получено</span></div><div class="achievement-grid">${items.map(a=>`<article class="${a.unlocked?'unlocked':'locked'}"><span>${a.unlocked?'🏆':'🔒'}</span><strong>${esc(a.title)}</strong><small>${a.unlocked?'Выполнено':`${a.current}/${a.target}`} · ${a.reward} ★</small></article>`).join('')}</div>`;return;
    }
    if(kind==='edit-profile'){
      body.innerHTML=`${panel('Профиль','Измени ник, который отображается в профиле и топе.')}<div class="form-field"><label>Новый ник · 2–24 символа</label><input id="nick" maxlength="24" value="${esc(state.user.nick.replace(/^@/,''))}" placeholder="Аноним"></div><div class="modal-actions"><button class="action" data-close-modal>Отмена</button><button class="action accent" id="saveNick">Сохранить</button></div>`;
      $('#saveNick').onclick=saveNick;bindClose(body);return
    }
    if(kind==='quests'){const d=await safe('/api/miniapp/quests',{},null);const items=d?.items||[];body.innerHTML=items.length?items.map(q=>`<article class="quest ${q.claimed?'claimed':''}"><div><strong>${esc(q.title)}</strong><b>${q.claimed?'Получено':`${q.current}/${q.target}`}</b></div><p>${q.claimed?`+${q.reward} ★ уже начислено`:q.done?'Награда начислится автоматически':`Награда: ${q.reward} ★`}</p><i class="progress"><i style="width:${Math.min(100,q.current/Math.max(1,q.target)*100)}%"></i></i></article>`).join(''):'<div class="empty">Сегодня заданий нет.</div>';return}
    if(kind==='streak'){const d=await safe('/api/miniapp/streak',{},null);if(d){state.stats.streak=d.current;state.stats.best_streak=d.best;render()}body.innerHTML=`${panel('Текущая серия',`<b>${state.stats.streak} дней</b> подряд. Серия не ограничена семью днями.`)}<div class="flame-grid">${Array.from({length:7},(_,i)=>`<i class="${i<Math.min(7,state.stats.streak)?'on':''}"></i>`).join('')}</div>${panel('Личный рекорд',`${state.stats.best_streak} дней. Активным считается день, когда ты общался в боте.`)}`;return}
    if(kind==='activity'){
      const d=await safe('/api/miniapp/activity',{},null)||{today:{},all:{}};
      body.innerHTML=['today','all'].map((k,i)=>`<section class="panel"><h3>${['Сегодня','За всё время'][i]}</h3><div class="kv-grid"><div class="kv"><small>Диалоги</small><strong>${d[k]?.dialogs||0}</strong></div><div class="kv"><small>Сообщения</small><strong>${d[k]?.messages||0}</strong></div><div class="kv"><small>Игры</small><strong>${d[k]?.games||0}</strong></div><div class="kv"><small>Хорошие оценки</small><strong>${d[k]?.good_ratings||0}</strong></div></div></section>`).join('');
      return
    }
    if(kind==='top'){const d=await safe('/api/miniapp/top',{},null);const items=d?.items||(!tg?.initData?[{place:1,nick:'Аноним-4821',rank:'Завсегдатай',stars:1380},{place:2,nick:'northwind',rank:'Свой человек',stars:1240},{place:3,nick:'Аноним-1520',rank:'Собеседник',stars:1110}]:[]);body.innerHTML=items.length?`<div class="top-list">${items.map(x=>`<div class="top-item"><i>${x.place}</i><span><strong>${esc(x.nick)}</strong><small>${esc(x.rank||'')}</small></span><b>${x.stars||0} ★</b></div>`).join('')}</div>`:'<div class="empty">В топе пока никого.</div>';return}
    if(kind==='referral'){body.innerHTML=`${panel('Твои приглашения',`Приглашено: <b>${state.referral.invited}</b> · Получено: <b>${state.referral.earned} ★</b>`)}<div class="copy-box"><input id="refLink" readonly value="${esc(state.referral_url)}"><button id="copyRef" aria-label="Скопировать">${svg('copy')}</button></div><p class="hint">Друг должен впервые запустить бота по этой ссылке.</p>`;$('#copyRef').onclick=copyReferral;return}
    if(kind==='settings'){await settings(body);return}
    if(kind==='feedback'){body.innerHTML=`${panel('Напиши команде','Сообщение уйдёт всем администраторам бота.')}<div class="form-field"><label>Сообщение · до 1000 символов</label><textarea id="feedback" maxlength="1000" placeholder="Что случилось или что можно улучшить?"></textarea></div><div class="modal-actions one"><button class="action accent" id="sendFeedback">Отправить</button></div>`;$('#sendFeedback').onclick=sendFeedback;return}
    if(kind==='rules'){
      body.innerHTML=`<section class="rules-card"><h3>Правила АНОН МГН</h3><blockquote><b>1. Без оскорблений и травли</b><p>Не унижай собеседника, не угрожай и не провоцируй конфликт.</p><b>2. Не сливай личную информацию</b><p>Нельзя отправлять чужие номера, адреса, фото, аккаунты и другие приватные данные без разрешения.</p><b>3. Без спама и запрещённого контента</b><p>Не отправляй рекламу, флуд, шок-контент и материалы 18+.</p><b>4. Увидел нарушение — отправь жалобу</b><p>Нажми <b>«Жалоба»</b> — сообщение попадёт модерации.</p></blockquote><i>Общайся нормально — и всё будет нормально.</i></section>`;return}
    if(kind==='chat-games'){
      body.innerHTML=`
        <div class="chat-game-picker">
          <button data-chat-game="words"><span>🗣</span><div><strong>Объясни слово</strong><small>Один объясняет, второй угадывает</small></div></button>
          <button data-chat-game="battle"><span>⚔️</span><div><strong>Битва мнений</strong><small>5 или 10 вопросов</small></div></button>
          <button data-chat-game="numbers"><span>🔢</span><div><strong>Числа</strong><small>Угадайте одинаковое число</small></div></button>
          <button data-chat-game="geo"><span>🗺</span><div><strong>GeoGuessr📍</strong><small>Угадай место в Магнитогорске</small></div></button>
        </div>`;
      $$('[data-chat-game]',body).forEach(b=>b.onclick=()=>{
        const game=b.dataset.chatGame;
        if(game==='words')inviteWords();
        else if(game==='battle'){closeModal();openModal('battle','Битва мнений','ИГРА ВДВОЁМ')}
        else if(game==='geo'){closeModal();openModal('geo','GeoGuessr📍','МАГНИТОГОРСК')}
        else{closeModal();openModal('numbers','Числа','ИГРА ВДВОЁМ')}
      });
      return;
    }
    if(kind==='battle'){body.innerHTML=`${panel('Битва мнений','Оба отвечают отдельно. Идеальное совпадение 5/5 или 10/10 даёт каждому 25 ★ базово. В x2/x3 награда умножается.')}<div class="modal-actions"><button class="action" data-battle="5">5 вопросов</button><button class="action accent" data-battle="10">10 вопросов</button></div>`;$$('[data-battle]',body).forEach(b=>b.onclick=()=>inviteBattle(+b.dataset.battle));return}
    if(kind==='numbers'){body.innerHTML=`${panel('Числа · 3 раунда','Точное совпадение даёт полную награду, близкое — половину. Лимитов по звёздам нет, x2/x3 применяется автоматически.')}<div class="modal-actions one"><button class="action" data-range="10">1–10 · 15 ★</button><button class="action" data-range="100">1–100 · 25 ★</button><button class="action accent" data-range="1000">1–1000 · 50 ★</button></div>`;$$('[data-range]',body).forEach(b=>b.onclick=()=>inviteNumbers(+b.dataset.range));return}
    if(kind==='geo'){
      body.innerHTML=`
        <section class="geo-intro">
          <div class="geo-intro-icon">🗺</div>
          <h3>Угадай Магнитогорск</h3>
          <p>Смотри фото и ставь точку там, где, по-твоему, находится это место.</p>
          <div class="geo-rules">
            <span>⏱ <b>2 минуты</b> на раунд</span>
            <span>⭐ Чем ближе — тем больше звёзд</span>
            <span>📍 Ответ отправляется через Telegram</span>
          </div>
          <div class="geo-safety"><b>Как ответить:</b><br>📎 Скрепка → Геопозиция → передвинь карту → выбери любую точку → отправь.<br><br><b>Можно поставить метку в любой точке карты.</b></div>
        </section>
        <div class="geo-round-choice">
          <button data-geo-rounds="3"><b>3</b><small>быстро</small></button>
          <button data-geo-rounds="5" class="selected"><b>5</b><small>оптимально</small></button>
          <button data-geo-rounds="10"><b>10</b><small>долго</small></button>
        </div>`;
      $$('[data-geo-rounds]',body).forEach(b=>b.onclick=()=>inviteGeo(+b.dataset.geoRounds));
      return;
    }
  }
  async function settings(body){
    const sub=await safe('/api/miniapp/subscription',{},null)||(!tg?.initData?state.subscription:null);state.subscription=sub;
    const themeBlock=`<div class="setting"><div><strong>Тема</strong><small>меняет акцент и поверхности</small></div><div class="theme-picker">${[['pink','Розовая'],['blue','Синяя'],['violet','Фиолетовая'],['green','Зелёная'],['orange','Оранжевая'],['mono','Ч/Б']].map(([v,t])=>`<button data-theme-choice="${v}" class="${(state.user.theme||'pink')===v?'active':''}">${t}</button>`).join('')}</div></div>`;
    body.innerHTML=`<div class="setting"><div><strong>Твой пол</strong><small>необязательно</small></div><div class="segments" id="gender"><button data-value="m">Парень</button><button data-value="f">Девушка</button><button data-value="">Не указывать</button></div></div><div class="setting"><div><strong>Кого ищешь</strong><small>предпочтение</small></div><div class="segments" id="looking"><button data-value="m">Парня</button><button data-value="f">Девушку</button><button data-value="">Неважно</button></div></div><div class="setting"><div><strong>Твой берег</strong><small>необязательно</small></div><select id="district"><option value="">Любой</option><option value="Правый берег">Правый берег</option><option value="Левый берег">Левый берег</option></select></div><div class="setting"><div><strong>Возраст</strong><small>необязательно · 13–20</small></div><input id="age" type="number" inputmode="numeric" min="13" max="20" placeholder="Не указан"></div>${themeBlock}${sub&&!sub.claimed?`<section class="panel reward"><span>${svg('gift')}</span><span><strong>${sub.amount} ★ за подписку</strong><small>Одноразовая награда</small></span><button id="subscribe">Получить</button></section>`:''}<section class="panel reward"><span>${svg('gift')}</span><span><strong>Поддержать проект</strong><small>Telegram Stars или СБП</small></span><button id="support">Поддержать</button></section><div class="modal-actions"><button class="action" id="resetSettings">Сбросить</button><button class="action accent" id="saveSettings">Сохранить</button></div><div class="modal-actions one"><button class="action danger" id="forget">Удалить профиль</button></div>`;
    $('#district').value=state.user.district||'';$('#age').value=state.user.age||'';
    $$('#gender button').forEach(b=>b.classList.toggle('active',b.dataset.value===(state.user.gender||'')));
    $$('#looking button').forEach(b=>b.classList.toggle('active',b.dataset.value===(state.user.looking_for||'')));
    $$('#gender button,#looking button').forEach(b=>b.onclick=()=>{$$('button',b.parentElement).forEach(x=>x.classList.remove('active'));b.classList.add('active')});
    $('#saveSettings').onclick=saveSettings;$('#resetSettings').onclick=resetSettings;$('#forget').onclick=confirmForget;$('#support').onclick=openSupport;
    if($('#subscribe'))$('#subscribe').onclick=claimSubscription;
    $$('[data-theme-choice]',body).forEach(b=>b.onclick=()=>setTheme(b.dataset.themeChoice,body));
  }
  function setTheme(theme,body){
    const allowed=new Set(['pink','blue','violet','green','orange','mono']);
    if(!allowed.has(theme))return;
    state.user.theme=theme;
    localStorage.setItem('anon_mgn_theme',theme);
    applyTheme();
    if(body)settings(body);
    haptic();
  }
  function bindClose(root=document){$$('[data-close-modal]',root).forEach(b=>b.onclick=closeModal)}
  async function saveNick(){
    const input=$('#nick');
    if(!input)return;
    const value=input.value.trim();
    const r=await safe('/api/miniapp/profile/nick',{method:'POST',body:JSON.stringify({nick:value})},null);
    if(!r)return;
    state.user.nick=r.nick||value;
    render();
    closeModal();
    toast('Ник сохранён');
    notify();
  }
  async function saveSettings(){const payload={age:+($('#age').value||0),district:$('#district').value,gender:$('#gender .active')?.dataset.value||'',looking_for:$('#looking .active')?.dataset.value||'',same_district:0};const r=await safe('/api/miniapp/settings',{method:'POST',body:JSON.stringify(payload)},null);if(r||!tg?.initData){state.user={...state.user,...payload,...(r?.user||{})};render();closeModal();toast('Настройки сохранены');notify()}}
  async function resetSettings(){const r=await safe('/api/miniapp/settings/reset',{method:'POST',body:'{}'},null);if(r||!tg?.initData){Object.assign(state.user,{age:0,district:'',gender:'',looking_for:''});render();settings($('#modalBody'));toast('Настройки сброшены')}}
  function confirmForget(){const body=$('#modalBody');body.innerHTML=`${panel('Удалить профиль?','Ник, звёзды, статистика и настройки будут удалены без возможности восстановления.')}<div class="modal-actions"><button class="action" id="cancelForget">Отмена</button><button class="action danger" id="doForget">Удалить</button></div>`;$('#cancelForget').onclick=()=>settings(body);$('#doForget').onclick=forgetProfile}
  async function forgetProfile(){const r=await safe('/api/miniapp/profile/forget',{method:'POST',body:'{}'},null);if(r){notify();try{tg?.close()}catch(_){location.reload()}}}
  async function claimSubscription(){if(!state.subscription)return;try{tg?.openTelegramLink?.(state.subscription.url)}catch(_){};toast('Подпишись и нажми ещё раз для проверки');const b=$('#subscribe');if(b){b.textContent='Проверить';b.onclick=async()=>{const r=await safe('/api/miniapp/subscription/claim',{method:'POST',body:'{}'},null);if(r){state.user.stars=r.stars;render();settings($('#modalBody'));toast(`+${r.amount} ★`);notify()}}}}
  function openPaymentUrl(url){
    try{if(typeof tg?.openLink==='function')tg.openLink(url);else window.open(url,'_blank','noopener')}catch(_){location.href=url}
  }
  function openSupport(){
    const body=$('#modalBody');
    body.innerHTML=`${panel('Поддержать проект','Выбери способ и сумму. Поддержка добровольная и не влияет на подбор собеседников.')}<div class="payment-tabs"><button class="active" data-support-method="stars">Telegram Stars</button><button data-support-method="sbp">СБП</button></div><div class="setting"><div><strong id="supportAmountTitle">Количество звёзд</strong><small id="supportAmountHint">от 1 до 10 000 ★</small></div><input id="supportAmount" type="number" inputmode="numeric" min="1" max="10000" step="1" value="100"></div><div class="modal-actions"><button class="action" id="supportBack">Назад</button><button class="action accent" id="supportPay">Оплатить ★</button></div>`;
    let method='stars';
    const select=m=>{method=m;$$('[data-support-method]',body).forEach(x=>x.classList.toggle('active',x.dataset.supportMethod===m));const input=$('#supportAmount');if(m==='stars'){input.min=1;input.max=10000;input.value=Math.max(1,Math.min(10000,+input.value||100));$('#supportAmountTitle').textContent='Количество звёзд';$('#supportAmountHint').textContent='от 1 до 10 000 ★';$('#supportPay').textContent='Оплатить ★'}else{input.min=1;input.removeAttribute('max');input.value=Math.max(1,+input.value||100);$('#supportAmountTitle').textContent='Сумма в рублях';$('#supportAmountHint').textContent='от 1 ₽';$('#supportPay').textContent='Оплатить по СБП'}};
    $$('[data-support-method]',body).forEach(x=>x.onclick=()=>select(x.dataset.supportMethod));
    $('#supportBack').onclick=()=>settings(body);
    $('#supportPay').onclick=()=>method==='stars'?paySupportStars():paySupportSbp();
  }
  async function paySupportStars(){
    if(!tg?.initData)return toast('Оплата доступна внутри Telegram');
    const stars=Number($('#supportAmount')?.value||0);if(!Number.isInteger(stars)||stars<1||stars>10000)return toast('Укажи от 1 до 10 000 ★');
    const button=$('#supportPay');if(button){button.disabled=true;button.textContent='Создаём счёт…'}
    const invoice=await safe('/api/miniapp/support/invoice',{method:'POST',body:JSON.stringify({stars})},null);
    if(!invoice?.invoice_url){if(button){button.disabled=false;button.textContent='Оплатить ★'};return}
    const finish=async status=>{if(status==='paid'){notify();toast(`Спасибо за поддержку · ${stars} ★`);await load();if(state.modal==='settings')settings($('#modalBody'));return}if(status==='pending'){toast('Платёж обрабатывается Telegram…');return}if(status==='failed')toast('Оплата не прошла');else if(status==='cancelled')toast('Оплата отменена');if(button){button.disabled=false;button.textContent='Оплатить ★'}};
    try{if(typeof tg?.openInvoice==='function')tg.openInvoice(invoice.invoice_url,finish);else tg?.openTelegramLink?.(invoice.invoice_url)}catch(_){if(button){button.disabled=false;button.textContent='Оплатить ★'};toast('Не удалось открыть оплату')}
  }
  async function paySupportSbp(){
    const amount=Number($('#supportAmount')?.value||0);if(!Number.isInteger(amount)||amount<1)return toast('Укажи сумму от 1 ₽');
    const p=await safe('/api/miniapp/payments/sbp',{method:'POST',body:JSON.stringify({kind:'support',amount_rub:amount})},null);
    if(!p?.payment_id)return;
    showSbpWaiting(p,'support');openPaymentUrl(p.pay_url);pollSbp(p.payment_id,'support');
  }
  function showSbpWaiting(p,kind){
    const body=$('#modalBody');if(!body)return;
    body.innerHTML=`${panel('Платёж по СБП',`Сумма: <b>${p.amount_rub} ₽</b>. После оплаты доступ обновится автоматически.`)}<div class="modal-actions"><button class="action" id="sbpOpen">Открыть оплату</button><button class="action accent" id="sbpCheck">Проверить оплату</button></div><p class="hint" id="sbpState">Ожидаем оплату…</p>`;
    $('#sbpOpen').onclick=()=>openPaymentUrl(p.pay_url);$('#sbpCheck').onclick=()=>checkSbp(p.payment_id,kind,true);
  }
  async function checkSbp(paymentId,kind,loud=false){
    const d=await safe(`/api/miniapp/payments/sbp/${encodeURIComponent(paymentId)}`,{},null);
    if(!d)return false;
    if(d.status==='paid'){
      if(sbpPollTimer){clearTimeout(sbpPollTimer);sbpPollTimer=null}
      await load();notify();toast('Спасибо за поддержку!');closeModal();
      return true;
    }
    const el=$('#sbpState');if(el)el.textContent='Платёж пока не подтверждён';
    if(loud)toast('Платёж пока не найден');
    return false;
  }
  function pollSbp(paymentId,kind){
    if(sbpPollTimer)clearTimeout(sbpPollTimer);
    let tries=0;const tick=async()=>{tries++;if(await checkSbp(paymentId,kind,false)||tries>=40)return;sbpPollTimer=setTimeout(tick,3000)};sbpPollTimer=setTimeout(tick,2500);
  }
  async function copyReferral(){try{await navigator.clipboard.writeText(state.referral_url);toast('Ссылка скопирована')}catch(_){$('#refLink').select();document.execCommand('copy');toast('Ссылка скопирована')}haptic()}
  async function sendFeedback(){const text=$('#feedback').value.trim();if(!text)return toast('Сначала напиши сообщение');const r=await safe('/api/miniapp/feedback',{method:'POST',body:JSON.stringify({text})},null);if(r||!tg?.initData){closeModal();toast('Сообщение отправлено');notify()}}
  async function updateSetting(key,value){const prev=state.user[key];state.user[key]=value;render();const payload={age:state.user.age||0,district:state.user.district||'',gender:state.user.gender||'',looking_for:state.user.looking_for||'',same_district:0};const r=await safe('/api/miniapp/settings',{method:'POST',body:JSON.stringify(payload)},null);if(!r&&tg?.initData){state.user[key]=prev;render()}else if(r?.user){state.user={...state.user,...r.user};render()}}
  function clearChatView(){
    chat.latest=0;chat.startedAt=0;chat.sent=0;chat.received=0;chat.seen.clear();
    chat.mediaCache.forEach(objectUrl=>{try{URL.revokeObjectURL(objectUrl)}catch(_){}});
    chat.mediaCache.clear();
    const list=$('#chatMessages');if(list)list.querySelectorAll('.chat-message,.chat-system,.game-invite,.game-round-card').forEach(x=>x.remove());
    const empty=$('#chatEmpty');if(empty)empty.hidden=false;
    $('#chatSent')&&($('#chatSent').textContent='0');$('#chatReceived')&&($('#chatReceived').textContent='0');
  }
  function formatChatDuration(){
    const el=$('#chatDuration');if(!el)return;
    if(!chat.startedAt){el.textContent='чат активен';return}
    const seconds=Math.max(0,Math.floor(Date.now()/1000-chat.startedAt));
    if(seconds<60)el.textContent='меньше минуты';
    else el.textContent=`${Math.max(1,Math.floor(seconds/60))} мин`;
  }
  function scrollChatBottom(){
    const list=$('#chatMessages');if(list)requestAnimationFrame(()=>{list.scrollTop=list.scrollHeight});
  }
  function audioTime(value){
    const total=Math.max(0,Math.floor(Number(value)||0));
    return `${Math.floor(total/60)}:${String(total%60).padStart(2,'0')}`;
  }
  function buildVoicePlayer(url){
    const wrap=document.createElement('div');wrap.className='voice-player';
    const play=document.createElement('button');play.type='button';play.className='voice-play';play.textContent='▶';
    const middle=document.createElement('div');middle.className='voice-middle';
    const wave=document.createElement('button');wave.type='button';wave.className='voice-wave';wave.setAttribute('aria-label','Перемотать');
    const bars=document.createElement('span');bars.className='voice-bars';
    for(let i=0;i<28;i++){const b=document.createElement('i');b.style.setProperty('--h',`${7+((i*17)%15)}px`);bars.appendChild(b)}
    const progress=document.createElement('span');progress.className='voice-progress';wave.append(bars,progress);
    const meta=document.createElement('div');meta.className='voice-meta';
    const current=document.createElement('span');current.textContent='0:00';
    const duration=document.createElement('span');duration.textContent='0:00';
    meta.append(current,duration);middle.append(wave,meta);
    const audio=document.createElement('audio');audio.preload='metadata';audio.src=url;audio.hidden=true;
    const setProgress=()=>{const d=audio.duration||0,p=d?Math.min(100,audio.currentTime/d*100):0;progress.style.width=`${p}%`;current.textContent=audioTime(audio.currentTime);duration.textContent=audioTime(d)};
    audio.addEventListener('loadedmetadata',setProgress);
    audio.addEventListener('durationchange',setProgress);
    audio.addEventListener('timeupdate',setProgress);
    audio.addEventListener('ended',()=>{play.textContent='▶';setProgress()});
    audio.addEventListener('pause',()=>{if(!audio.ended)play.textContent='▶'});
    audio.addEventListener('play',()=>{play.textContent='❚❚'});
    audio.addEventListener('error',()=>{wrap.classList.add('error');middle.innerHTML='<span class="media-error">Голосовое недоступно</span>'});
    play.onclick=()=>{if(audio.paused)audio.play().catch(()=>toast('Не удалось воспроизвести голосовое'));else audio.pause()};
    wave.onclick=e=>{const r=wave.getBoundingClientRect();if(audio.duration)audio.currentTime=Math.max(0,Math.min(audio.duration,(e.clientX-r.left)/r.width*audio.duration))};
    wrap.append(play,middle,audio);
    return wrap;
  }
  function gameKey(data={}){return `${data.game_type||''}:${data.game_id||0}`}
  function renderGameInvite(event,list){
    const data=event.data||{},key=gameKey(data);
    const card=document.createElement('div');card.className=`game-invite ${event.mine?'mine':''}`;card.dataset.gameKey=key;
    const icon=document.createElement('div');icon.className='game-invite-icon';icon.textContent=({geo:'📍',battle:'⚔️',numbers:'🔢',words:'🗣️'}[String(data.game_type||'')]||'🎮');
    const copy=document.createElement('div');copy.className='game-invite-copy';
    const title=document.createElement('strong');title.textContent=(event.text||'Игра').replace(/^[^\p{L}\p{N}]+/u,'').trim()||'Игра';
    const sub=document.createElement('small');sub.textContent=data.subtitle||'Игра с собеседником';
    const status=document.createElement('span');status.className='game-invite-status';status.textContent=event.mine?'Приглашение отправлено':'Собеседник предлагает сыграть';
    copy.append(title,sub,status);card.append(icon,copy);
    if(!event.mine){
      const actions=document.createElement('div');actions.className='game-invite-actions';
      const no=document.createElement('button');no.type='button';no.textContent='Не сейчас';
      const yes=document.createElement('button');yes.type='button';yes.className='accept';yes.textContent='Принять';
      no.onclick=()=>respondGameInvite(card,data,false);
      yes.onclick=()=>respondGameInvite(card,data,true);
      actions.append(no,yes);card.append(actions);
    }
    list.appendChild(card);scrollChatBottom();
  }
  function applyGameStatus(event,list){
    const data=event.data||{},key=gameKey(data),card=list.querySelector(`[data-game-key="${CSS.escape(key)}"]`);
    if(card){
      card.querySelector('.game-invite-actions')?.remove();
      const status=card.querySelector('.game-invite-status');
      if(status){status.textContent=event.text||data.status||'Обновлено';status.classList.add(data.status||'done')}
    }else{
      const el=document.createElement('div');el.className='chat-system';el.textContent=event.text||'Статус игры обновлён';list.appendChild(el);
    }
    scrollChatBottom();
  }
  async function respondGameInvite(card,data,accept){
    const buttons=card.querySelectorAll('button');buttons.forEach(b=>b.disabled=true);
    try{
      const result=await request('/api/miniapp/games/respond',{method:'POST',body:JSON.stringify({
        game_type:data.game_type,game_id:data.game_id,accept:Boolean(accept)
      })});
      card.querySelector('.game-invite-actions')?.remove();
      const status=card.querySelector('.game-invite-status');
      if(status){status.textContent=accept?'Принято · игра началась':'Предложение отклонено';status.classList.add(accept?'accepted':'declined')}
      toast(accept?'Игра началась':'Предложение отклонено');notify(accept?'success':'warning');await syncChat(false);
    }catch(e){buttons.forEach(b=>b.disabled=false);toast(e.message)}
  }

  function openPhotoViewer(url){
    const viewer=$('#photoViewer'),img=$('#photoViewerImage');if(!viewer||!img)return;
    img.src=url;viewer.hidden=false;document.body.classList.add('viewer-open');haptic();
  }
  function closePhotoViewer(){
    const viewer=$('#photoViewer'),img=$('#photoViewerImage');if(!viewer||!img)return;
    viewer.hidden=true;img.src='';document.body.classList.remove('viewer-open');
  }
  function replyPreviewForEvent(event){
    if(event.kind==='photo')return event.text||'Фото';
    if(event.kind==='voice')return 'Голосовое';
    if(event.kind==='sticker')return event.text||'Стикер';
    return event.text||'Сообщение';
  }
  function clearReply(){
    chat.reply=null;
    const box=$('#replyPreview');if(box)box.hidden=true;
    const text=$('#replyText');if(text)text.textContent='';
  }
  function setReply(event){
    if(!event||['system','game_invite','game_status','game_round'].includes(event.kind))return;
    const preview=String(replyPreviewForEvent(event)||'Сообщение').replace(/\s+/g,' ').trim().slice(0,160);
    chat.reply={event_id:Number(event.id)||0,text:preview};
    const box=$('#replyPreview'),text=$('#replyText');
    if(text)text.textContent=preview;
    if(box)box.hidden=false;
    $('#chatInput')?.focus();
    haptic('light');
  }
  function bindReplyGesture(row,event){
    let startX=0,startY=0;
    row.addEventListener('touchstart',e=>{const t=e.touches?.[0];if(t){startX=t.clientX;startY=t.clientY}},{passive:true});
    row.addEventListener('touchend',e=>{
      const t=e.changedTouches?.[0];if(!t)return;
      const dx=t.clientX-startX,dy=Math.abs(t.clientY-startY);
      if(dx>54&&dy<40)setReply(event);
    },{passive:true});
    row.ondblclick=()=>setReply(event);
  }

  async function attachMediaToEvent(node,event){
    if(!event.media_url)return;
    const url=apiBase+event.media_url;
    if(event.kind==='photo'){
      const img=document.createElement('img');
      img.className='chat-photo';
      img.alt='';
      img.src=url;
      img.onload=scrollChatBottom;
      img.onclick=()=>openPhotoViewer(url);
      img.onerror=()=>{img.remove();const e=document.createElement('span');e.className='media-error';e.textContent='Фото не загрузилось';node.prepend(e)};
      node.prepend(img);
    }else if(event.kind==='voice'){
      node.prepend(buildVoicePlayer(url));
    }else if(event.kind==='sticker'){
      const img=document.createElement('img');
      img.className='chat-sticker';
      img.alt=event.text||'';
      img.src=url;
      img.onload=scrollChatBottom;
      img.onerror=()=>img.remove();
      node.prepend(img);
    }
  }
  function appendChatEvent(event){
    if(!event||chat.seen.has(event.id))return;
    chat.seen.add(event.id);
    const list=$('#chatMessages');if(!list)return;
    const empty=$('#chatEmpty');if(empty)empty.hidden=true;
    if(event.kind==='game_invite'){renderGameInvite(event,list);return}
    if(event.kind==='game_status'){applyGameStatus(event,list);return}
    if(event.kind==='game_round'){
      const el=document.createElement('div');el.className='game-round-card';
      el.textContent=(event.text||'').replace(/<[^>]*>/g,'');
      list.appendChild(el);scrollChatBottom();return;
    }
    if(event.kind==='system'){
      const el=document.createElement('div');el.className='chat-system';el.textContent=event.text||'';list.appendChild(el);scrollChatBottom();return;
    }
    const row=document.createElement('div');row.className=`chat-message ${event.mine?'mine':'theirs'}`;
    const bubble=document.createElement('div');bubble.className='chat-bubble';
    const reply=event.data?.reply;
    if(reply?.text){
      const quote=document.createElement('div');quote.className='reply-quote';quote.textContent=reply.text;bubble.appendChild(quote);
    }
    if(event.text){
      const p=document.createElement('p');p.textContent=event.text;bubble.appendChild(p);
    }
    const time=document.createElement('small');
    const dt=new Date((event.created_at||Math.floor(Date.now()/1000))*1000);
    time.textContent=dt.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});
    bubble.appendChild(time);row.appendChild(bubble);list.appendChild(row);
    bindReplyGesture(row,event);
    attachMediaToEvent(bubble,event);scrollChatBottom();
  }
  function gameAction(payload){
    return request('/api/miniapp/games/action',{method:'POST',body:JSON.stringify(payload)});
  }
  function formatGeoDistance(value){
    const m=Number(value);
    if(!Number.isFinite(m))return '—';
    if(m<1000)return `${Math.max(0,Math.round(m))} м`;
    return `${(m/1000).toFixed(1).replace('.',',')} км`;
  }
  function stopGeoTimer(){
    if(chat.geoTimer){clearInterval(chat.geoTimer);chat.geoTimer=null}
  }
  function startGeoTimer(deadline){
    stopGeoTimer();
    const tick=()=>{
      const el=$('[data-geo-timer]');
      if(!el)return stopGeoTimer();
      const left=Math.max(0,Number(deadline||0)*1000-Date.now());
      const sec=Math.ceil(left/1000),min=Math.floor(sec/60),rest=sec%60;
      el.textContent=`${min}:${String(rest).padStart(2,'0')}`;
      el.classList.toggle('ending',sec<=20);
      if(sec<=0){stopGeoTimer();setTimeout(()=>syncChat(false),500)}
    };
    tick();chat.geoTimer=setInterval(tick,1000);
  }
  function renderActiveGame(game){
    const root=$('#activeGame');if(!root)return;
    const geoLocksChat=!!(game&&game.type==='geo'&&['active','round_done'].includes(game.status));
    const nextButton=$('#chatNext'),stopButton=$('#chatStop');
    if(nextButton)nextButton.hidden=geoLocksChat;
    if(stopButton)stopButton.hidden=geoLocksChat;
    if(!game){
      if(chat.gameHoldUntil>Date.now())return;
      stopGeoTimer();
      chat.game=null;root.hidden=true;root.innerHTML='';return;
    }
    if(game.type!=='geo')stopGeoTimer();
    chat.game=game;
    if(game.finished)chat.gameHoldUntil=Date.now()+6000;
    root.hidden=false;
    const top=`<header><span><small>${game.type==='battle'?'БИТВА МНЕНИЙ':game.type==='numbers'?'ЧИСЛА':game.type==='geo'?'GeoGuessr📍':'ОБЪЯСНИ СЛОВО'}</small><strong>Раунд ${game.round||1}/${game.total||1}</strong></span><button type="button" data-game-collapse>×</button></header>`;

    if(game.status==='invited'){
      root.innerHTML=top+`<div class="active-game-body"><p>${game.inviter?'Ждём ответ собеседника…':'Собеседник предлагает сыграть. Ответь на карточке приглашения выше.'}</p></div>`;
      root.querySelector('[data-game-collapse]').onclick=()=>{root.hidden=true};
      return;
    }

    if(game.type==='battle'){
      const opts=game.options||[];
      let body=`<div class="active-game-body"><h3>${esc(game.question||'Вопрос')}</h3>`;
      if(game.status==='active'){
        if(game.answered){
          body+=`<div class="game-wait">✓ Ответ принят · ждём собеседника</div>`;
        }else{
          body+=`<div class="battle-options">
            <button type="button" data-battle-choice="0">${esc(opts[0]||'Вариант 1')}</button>
            <button type="button" data-battle-choice="1">${esc(opts[1]||'Вариант 2')}</button>
          </div>`;
        }
      }else if(game.status==='round_done'||game.finished){
        const mine=game.my_answer,other=game.partner_answer;
        body+=`<div class="game-result ${game.matched?'match':'miss'}">
          <strong>${game.matched?'🤝 Совпало':'💥 Разошлись'}</strong>
          <span>Ты: <b>${mine==null?'—':esc(opts[mine]||String(mine))}</b></span>
          <span>Собеседник: <b>${other==null?'—':esc(opts[other]||String(other))}</b></span>
          <small>Совпадений: ${game.matches||0}/${game.total||0}</small>
        </div>`;
        if(game.can_next)body+=`<button class="game-next" type="button" data-game-next>Следующий вопрос</button>`;
        if(game.finished)body+=`<div class="game-finished">🏁 Игра окончена</div>`;
      }
      body+='</div>';root.innerHTML=top+body;
      $$('[data-battle-choice]',root).forEach(b=>b.onclick=async()=>{
        $$('[data-battle-choice]',root).forEach(x=>x.disabled=true);
        try{
          const r=await gameAction({game_type:'battle',game_id:game.id,action:'answer',choice:+b.dataset.battleChoice});
          if(r?.game)renderActiveGame(r.game);await syncChat(false);haptic();
        }catch(e){toast(e.message);renderActiveGame(game)}
      });
    }else if(game.type==='numbers'){
      let body=`<div class="active-game-body"><h3>Выбери число от 1 до ${game.range_max||10}</h3>`;
      if(game.status==='active'){
        if(game.answered){
          body+=`<div class="game-wait">✓ Число принято · ждём собеседника</div>`;
        }else{
          body+=`<form class="number-game-form" id="numberGameForm">
            <input id="numberGameValue" type="number" inputmode="numeric" min="1" max="${game.range_max||10}" placeholder="1–${game.range_max||10}">
            <button type="submit">Выбрать</button>
          </form>`;
        }
      }else if(game.status==='round_done'||game.finished){
        body+=`<div class="game-result ${game.matched?'match':'miss'}">
          <strong>${game.matched?'🎯 Точное совпадение':'🔢 Результат'}</strong>
          <span>Ты: <b>${game.my_answer??'—'}</b></span>
          <span>Собеседник: <b>${game.partner_answer??'—'}</b></span>
          <small>Разница: ${game.difference??0} · точных: ${game.matches||0}/${game.total||3}</small>
        </div>`;
        if(game.can_next)body+=`<button class="game-next" type="button" data-game-next>Следующий раунд</button>`;
        if(game.finished)body+=`<div class="game-finished">🏁 Игра окончена · получено ${game.reward_total||0} ★</div>`;
      }
      body+='</div>';root.innerHTML=top+body;
      const form=$('#numberGameForm',root);if(form)form.onsubmit=async e=>{
        e.preventDefault();const input=$('#numberGameValue',root),value=+(input?.value||0);
        if(value<1||value>(game.range_max||10))return toast(`Число от 1 до ${game.range_max||10}`);
        form.querySelector('button').disabled=true;
        try{
          const r=await gameAction({game_type:'numbers',game_id:game.id,action:'answer',value});
          if(r?.game)renderActiveGame(r.game);await syncChat(false);haptic();
        }catch(err){toast(err.message);form.querySelector('button').disabled=false}
      };
    }else if(game.type==='geo'){
      let body=`<div class="active-game-body geo-active">`;
      if(game.image_url)body+=`<div class="geo-game-photo"><img src="${esc(game.image_url)}" alt="Место в Магнитогорске"></div>`;
      if(game.status==='active'){
        body+=`
          <div class="geo-live-head"><span>⏱ Осталось</span><strong data-geo-timer>2:00</strong></div>
          <div class="geo-instructions">
            <strong>📍 Отправь выбранную точку через Telegram</strong>
            <p>📎 Скрепка → <b>Геопозиция</b> → передвинь карту → выбери любую точку → отправь.</p>
          </div>
          <div class="geo-warning">🌍 Игра принимает любую корректную точку на карте.</div>`;
        if(game.answered){
          body+=`<div class="game-wait">✅ Метка принята · ждём собеседника</div>`;
        }else{
          body+=`<button class="geo-open-telegram" type="button" data-geo-telegram>Открыть Telegram для ответа</button>`;
        }
        body+=`<div class="geo-stars-hint">⭐ Чем ближе к месту — тем больше звёзд · базово до 10 ★ · x2/x3 применяется</div>`;
      }else if(game.status==='round_done'||game.finished){
        body+=`<div class="game-result geo-result">
          <strong>📍 ${esc(game.place_title||'Результат раунда')}</strong>
          <span>Твоя ошибка: <b>${formatGeoDistance(game.my_distance)}</b></span>
          <span>Собеседник: <b>${formatGeoDistance(game.partner_distance)}</b></span>
          <small>✨ За игру: ${game.reward_total||0} ★</small>
        </div>`;
        if(game.source_url)body+=`<a class="geo-source" href="${esc(game.source_url)}" target="_blank" rel="noopener">Источник фото · ${esc(game.license||'лицензия')}</a>`;
        if(game.can_next)body+=`<button class="game-next" type="button" data-game-next>Следующее место</button>`;
        if(game.finished)body+=`<div class="game-finished">🏁 GeoGuessr📍 окончен · получено ${game.reward_total||0} ★</div>`;
      }
      body+='</div>';root.innerHTML=top+body;
      if(game.status==='active')startGeoTimer(game.deadline);
      const telegram=$('[data-geo-telegram]',root);if(telegram)telegram.onclick=()=>{
        haptic('medium');
        toast('В Telegram: 📎 → Геопозиция → выбери точку на карте');
        setTimeout(()=>{try{tg?.close()}catch(_){}},250);
      };
    }else if(game.type==='words'){
      let body=`<div class="active-game-body words-game">`;
      if(game.status==='active'){
        body+=game.role==='explainer'
          ?`<small>ТВОЁ СЛОВО</small><div class="secret-word">${esc(game.word||'')}</div><p>Объясни его сообщениями, но не называй само слово.</p>`
          :`<small>ТЫ УГАДЫВАЕШЬ</small><h3>Слушай объяснение собеседника</h3><p>Пиши догадки прямо в обычное поле сообщения ниже.</p>`;
      }else if(game.status==='round_done'){
        body+=`<div class="game-result match"><strong>🎯 Слово угадано</strong><small>Угадано слов: ${game.correct||0}</small></div><button class="game-next" type="button" data-game-next>Следующее слово</button>`;
      }else if(game.finished){
        body+=`<div class="game-finished">🏁 Игра окончена · угадано ${game.correct||0}/${game.total||5}</div>`;
      }
      body+='</div>';root.innerHTML=top+body;
    }

    const next=$('[data-game-next]',root);if(next)next.onclick=async()=>{
      next.disabled=true;
      try{
        const r=await gameAction({game_type:game.type,game_id:game.id,action:'next'});
        if(r?.game)renderActiveGame(r.game);await syncChat(false);notify();
      }catch(e){toast(e.message);next.disabled=false}
    };
    const close=$('[data-game-collapse]',root);if(close)close.onclick=()=>{root.hidden=true};
  }

  async function syncChat(force=false){
    if(!tg?.initData||state.status!=='paired')return false;
    try{
      const data=await request(`/api/miniapp/chat/state?after=${force?chat.latest:chat.latest}&_=${Date.now()}`);
      if(data.status!=='paired'){
        applyStatusSnapshot(data);
        return false;
      }
      if(data.started_at && chat.startedAt && Number(data.started_at)!==Number(chat.startedAt))clearChatView();
      chat.startedAt=Number(data.started_at||chat.startedAt||0);
      chat.sent=Number(data.sent||0);chat.received=Number(data.received||0);
      $('#chatSent')&&($('#chatSent').textContent=String(chat.sent));
      $('#chatReceived')&&($('#chatReceived').textContent=String(chat.received));
      const peerName=$('#chatPeer strong');
      if(peerName)peerName.textContent=data.peer?.nick?(data.peer.nick+(data.peer.emoji?' '+data.peer.emoji:'')):'Собеседник';
      (data.events||[]).forEach(appendChatEvent);
      chat.latest=Math.max(chat.latest,Number(data.latest||0),...(data.events||[]).map(x=>Number(x.id||0)));
      renderActiveGame(data.game||null);
      formatChatDuration();
      return true;
    }catch(e){
      if(force)toast(e.message);
      return false;
    }
  }
  function startChatSync(){
    if(chat.timer||!tg?.initData)return;
    chat.timer=setInterval(()=>{if(!document.hidden&&state.status==='paired'){formatChatDuration();if(!realtimeConnected)syncChat(false)}},8000);
  }
  function stopChatSync(){if(chat.timer){clearInterval(chat.timer);chat.timer=null}}
  async function sendChatText(){
    const input=$('#chatInput');if(!input)return;
    const text=input.value.trim();if(!text)return;
    const button=$('#chatSend');if(button)button.disabled=true;
    try{
      await request('/api/miniapp/chat/text',{method:'POST',body:JSON.stringify({text,reply:chat.reply})});
      input.value='';input.style.height='auto';clearReply();await syncChat(false);haptic();
    }catch(e){toast(e.message)}
    finally{if(button)button.disabled=false}
  }
  async function sendChatPhoto(file){
    if(!file)return;
    if(file.size>8*1024*1024)return toast('Фото максимум 8 МБ');
    const form=new FormData();form.append('file',file,file.name||'photo.jpg');
    try{await upload('/api/miniapp/chat/photo',form);await syncChat(false);notify()}
    catch(e){toast(e.message)}
    finally{const input=$('#photoInput');if(input)input.value=''}
  }
  async function sendVoiceBlob(blob){
    if(!blob||!blob.size)return;
    if(blob.size>12*1024*1024)return toast('Голосовое слишком большое');
    const ext=blob.type.includes('mp4')?'m4a':blob.type.includes('ogg')?'ogg':'webm';
    const form=new FormData();form.append('file',blob,`voice.${ext}`);
    try{await upload('/api/miniapp/chat/voice',form);await syncChat(false);notify()}
    catch(e){toast(e.message)}
  }
  async function toggleVoiceRecording(){
    const btn=$('#micButton');if(!btn)return;
    if(chat.recording){
      chat.recording=false;btn.classList.remove('recording');clearTimeout(chat.recordTimer);chat.recordTimer=null;
      try{chat.recorder?.stop()}catch(_){}
      return;
    }
    if(!navigator.mediaDevices?.getUserMedia||typeof MediaRecorder==='undefined'){
      toast('Открою системную запись');
      $('#voiceInput')?.click();
      return;
    }
    try{
      chat.stream=await navigator.mediaDevices.getUserMedia({audio:true});
      const types=['audio/mp4','audio/ogg;codecs=opus','audio/webm;codecs=opus','audio/webm'];
      const mime=types.find(x=>MediaRecorder.isTypeSupported?.(x))||'';
      chat.chunks=[];
      chat.recorder=new MediaRecorder(chat.stream,mime?{mimeType:mime}:undefined);
      chat.recorder.ondataavailable=e=>{if(e.data?.size)chat.chunks.push(e.data)};
      chat.recorder.onstop=()=>{
        const blob=new Blob(chat.chunks,{type:chat.recorder?.mimeType||mime||'audio/webm'});
        chat.stream?.getTracks().forEach(t=>t.stop());chat.stream=null;chat.recorder=null;chat.chunks=[];
        sendVoiceBlob(blob);
      };
      chat.recorder.start();chat.recording=true;btn.classList.add('recording');toast('Запись голосового… нажми ещё раз для отправки');haptic('medium');
      chat.recordTimer=setTimeout(()=>{if(chat.recording)toggleVoiceRecording()},60000);
    }catch(_){
      toast('Открою системную запись');
      $('#voiceInput')?.click();
    }
  }
  async function loadStickers(){
    const tray=$('#stickerTray'),grid=$('#stickerGrid'),emojiGrid=$('#emojiGrid'),section=$('#stickerSection');
    if(!tray||!grid||!emojiGrid)return;
    tray.hidden=!tray.hidden;
    if(tray.hidden)return;

    if(!emojiGrid.childElementCount){
      CHAT_EMOJIS.forEach(emoji=>{
        const b=document.createElement('button');
        b.type='button';b.className='emoji-item';b.textContent=emoji;
        b.onclick=()=>{
          const input=$('#chatInput');if(!input)return;
          const start=input.selectionStart??input.value.length,end=input.selectionEnd??start;
          input.setRangeText(emoji,start,end,'end');input.focus();haptic();
        };
        emojiGrid.appendChild(b);
      });
    }

    if(chat.stickersLoaded)return;
    grid.innerHTML='<div class="sticker-loading">Загрузка стикеров…</div>';
    const data=await safe('/api/miniapp/chat/stickers',{},null);
    grid.innerHTML='';
    const items=data?.items||[];
    if(!items.length){
      if(section)section.hidden=true;
      return;
    }
    if(section)section.hidden=false;
    chat.stickersLoaded=true;
    items.forEach(item=>{
      const b=document.createElement('button');b.type='button';b.className='sticker-item';b.title=item.emoji||'Стикер';
      const img=document.createElement('img');img.alt=item.emoji||'';b.appendChild(img);grid.appendChild(b);
      mediaBlobUrl(item.url).then(url=>img.src=url).catch(()=>{b.textContent=item.emoji||'🙂'});
      b.onclick=async()=>{
        tray.hidden=true;
        try{await request('/api/miniapp/chat/sticker',{method:'POST',body:JSON.stringify({id:item.id})});await syncChat(false);haptic()}
        catch(e){toast(e.message)}
      };
    });
  }

  function confirmLongChat(action){
    if(!chat.startedAt||Date.now()/1000-chat.startedAt<300)return Promise.resolve(true);
    const message=`Диалог идёт уже ${Math.max(5,Math.floor((Date.now()/1000-chat.startedAt)/60))} мин. Точно ${action}?`;
    if(tg?.showConfirm)return new Promise(resolve=>{try{tg.showConfirm(message,resolve)}catch(_){resolve(window.confirm(message))}});
    return Promise.resolve(window.confirm(message));
  }
  async function stopChat(){
    if(!(await confirmLongChat('завершить чат')))return;
    try{
      const data=await request('/api/miniapp/chat/stop',{method:'POST',body:'{}'});
      clearChatView();applyStatusSnapshot(data);go('home');notify();
      if(data.result)showDialogResult(data.result);else toast('Диалог завершён');
      await loadNotifications(false);
    }catch(e){toast(e.message)}
  }
  async function nextChat(){
    if(!(await confirmLongChat('найти следующего')))return;
    try{
      clearChatView();
      const data=await request('/api/miniapp/chat/next',{method:'POST',body:'{}'});
      applyStatusSnapshot(data);
      if(state.status==='paired')go('chat');else go('search');
      notify();
      if(data.result)showDialogResult(data.result);
      else toast(state.status==='paired'?'Новый собеседник найден':'Ищем нового собеседника');
      await loadNotifications(false);
    }catch(e){toast(e.message)}
  }

  async function toggleSearch(){
    if(searchBusy)return;
    searchBusy=true;renderSearch();
    try{
      await syncStatus(true);
      const action=$('#searchToggle').dataset.action;
      if(action==='chat'){go('chat');return}
      const path=action==='stop'?'/api/miniapp/search/stop':'/api/miniapp/search/start';
      const seq=++statusRequestSeq;
      const data=await request(path,{method:'POST',body:'{}'});
      applyStatusSnapshot(data,seq);
      await syncStatus(true);
      notify();
      toast(state.status==='paired'?'Чат активен':state.status==='queued'?'Поиск запущен':'Поиск остановлен');
    }catch(e){
      toast(e.message);
      await syncStatus(true);
    }finally{
      searchBusy=false;
      renderSearch();
    }
  }
  async function inviteWords(){
    const r=await safe('/api/miniapp/games/words/invite',{method:'POST',body:'{}'},null);
    if(r){closeModal();toast(r.message||'Приглашение отправлено');notify();syncChat(false)}
  }
  async function inviteBattle(total){const r=await safe('/api/miniapp/games/battle/invite',{method:'POST',body:JSON.stringify({total})},null);if(r||!tg?.initData){closeModal();toast(r?.message||'Приглашение отправлено');notify();syncChat(false)}}
  async function inviteNumbers(range_max){const r=await safe('/api/miniapp/games/numbers/invite',{method:'POST',body:JSON.stringify({range_max})},null);if(r||!tg?.initData){closeModal();toast(r?.message||'Приглашение отправлено');notify();syncChat(false)}}
  async function inviteGeo(rounds){const r=await safe('/api/miniapp/games/geo/invite',{method:'POST',body:JSON.stringify({rounds})},null);if(r||!tg?.initData){closeModal();toast(r?.message||'Приглашение в GeoGuessr📍 отправлено');notify();syncChat(false)}}
  function bind(){
    document.addEventListener('click',e=>{const nav=e.target.closest('[data-nav]');if(nav)go(nav.dataset.nav);const open=e.target.closest('[data-open]');if(open){const labels={'settings':'Настройки','edit-profile':'Изменить профиль','quests':'Цели дня','streak':'Серия активности','activity':'Моя активность','top':'Топ 10','referral':'Приглашения','feedback':'Обратная связь','rules':'Правила'};openModal(open.dataset.open,labels[open.dataset.open]||'АНОН МГН')}const game=e.target.closest('[data-game]');if(game){if(game.dataset.game==='words')inviteWords();else openModal(game.dataset.game,game.dataset.game==='battle'?'Битва мнений':game.dataset.game==='geo'?'GeoGuessr📍':'Числа',game.dataset.game==='geo'?'МАГНИТОГОРСК':'ИГРА ВДВОЁМ')}});
    $$('[data-close-modal]').forEach(b=>b.onclick=closeModal);
    $('#searchToggle').onclick=toggleSearch;
    $$('[data-setting] button').forEach(b=>b.onclick=()=>updateSetting(b.parentElement.dataset.setting,b.dataset.value));
    $$('#eventFilter button').forEach(b=>b.onclick=()=>{$$('#eventFilter button').forEach(x=>x.classList.remove('active'));b.classList.add('active');renderEvents(b.dataset.filter)});
    $$('#topPeriods button').forEach(b=>b.onclick=()=>{haptic();loadTopPage(b.dataset.topPeriod)});
    const composer=$('#chatComposer');if(composer)composer.onsubmit=e=>{e.preventDefault();sendChatText()};
    const input=$('#chatInput');if(input){input.addEventListener('input',()=>{input.style.height='auto';input.style.height=`${Math.min(100,input.scrollHeight)}px`});input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!/iPhone|iPad|Android/i.test(navigator.userAgent)){e.preventDefault();sendChatText()}})}
    $('#replyCancel')&&($('#replyCancel').onclick=clearReply);
    $('#photoButton')&&($('#photoButton').onclick=()=>$('#photoInput')?.click());
    $('#photoInput')&&($('#photoInput').onchange=e=>sendChatPhoto(e.target.files?.[0]));
    $('#stickerButton')&&($('#stickerButton').onclick=loadStickers);
    $('#micButton')&&($('#micButton').onclick=toggleVoiceRecording);
    $('#voiceInput')&&($('#voiceInput').onchange=e=>{const file=e.target.files?.[0];if(file)sendVoiceBlob(file);e.target.value=''});
    $('#chatGames')&&($('#chatGames').onclick=()=>openModal('chat-games','Игры','В АКТИВНОМ ЧАТЕ'));
    $('#chatPeer')&&($('#chatPeer').onclick=openReport);
    $('#chatStop')&&($('#chatStop').onclick=stopChat);
    $('#chatNext')&&($('#chatNext').onclick=nextChat);
    $('#photoViewerClose')&&($('#photoViewerClose').onclick=closePhotoViewer);
    $('#photoViewer')&&($('#photoViewer').onclick=e=>{if(e.target.id==='photoViewer')closePhotoViewer()});
    window.addEventListener('online',()=>{$('#offline').hidden=true;if(tg?.initData){load();syncStatus(true);if(state.status==='paired')syncChat(true)}});
    window.addEventListener('offline',()=>{if(tg?.initData)$('#offline').hidden=false});
    window.addEventListener('focus',()=>{syncStatus(true);if(state.status==='paired')syncChat(true)});
    window.addEventListener('pageshow',()=>{syncStatus(true);if(state.status==='paired')syncChat(true)});
    document.addEventListener('visibilitychange',()=>{if(!document.hidden){syncStatus(true);if(state.status==='paired')syncChat(true)}});
    try{if(tgAtLeast('6.1'))tg.BackButton.onClick(()=>state.modal?closeModal():state.page!=='home'?go('home'):tg.close())}catch(_){}
  }
  async function boot(){
    const bootEl=$('#boot'),appEl=$('#app');
    const watchdog=setTimeout(()=>{bootEl?.classList.add('hide');appEl?.classList.add('ready')},6500);
    try{
      icons();
      try{tg?.ready();tg?.expand();if(tgAtLeast('6.1')){tg.setHeaderColor?.('#050506');tg.setBackgroundColor?.('#050506')}if(tgAtLeast('7.7'))tg.disableVerticalSwipes?.()}catch(_){}
      bind();
      await load();
      await syncStatus(true);
      startRealtime();
      startStatusSync();
      if(state.status==='paired')go('chat');
      else await loadDialogResult(true);
    }catch(e){
      console.error('Mini App boot failed',e);
      if(tg?.initData)toast(e?.message||'Ошибка запуска Mini App');
    }finally{
      clearTimeout(watchdog);
      appEl?.classList.add('ready');
      setTimeout(()=>bootEl?.classList.add('hide'),180);
    }
  }
  boot();
})();

}
