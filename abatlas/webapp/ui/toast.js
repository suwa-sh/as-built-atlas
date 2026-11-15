// 汎用部品: 画面の右下に出す知らせ

const $toast = document.getElementById("toast");

export function toast(msg, ms = 6000) {
  $toast.textContent = msg;
  $toast.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => ($toast.hidden = true), ms);
}
