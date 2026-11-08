// The hit card's Copy passage with citation (Brian, 2026-11-06): the
// passage and its citation, fetched from the server that wrote them, put
// on the clipboard, and the entry's label changed to the word the page
// carries for a moment. No preview. The entry is drawn only once this
// marks the page as able to copy, so a page without a script or a
// clipboard shows none. No sentence here: the words are the server's.
if (navigator.clipboard) document.documentElement.classList.add("can-copy");

document.addEventListener("click", async (event) => {
  const entry = event.target.closest("button.copy-citation");
  if (!entry || !navigator.clipboard) return;
  const answer = await fetch(entry.dataset.text, { credentials: "same-origin" });
  if (!answer.ok) return;
  await navigator.clipboard.writeText(await answer.text());
  const label = entry.querySelector("span");
  if (!label) return;
  const was = label.textContent;
  label.textContent = entry.dataset.copied;
  setTimeout(() => { label.textContent = was; }, 1500);
});
