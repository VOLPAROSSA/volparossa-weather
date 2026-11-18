// Keep the film outside the browsing context until the visitor opens its cover.
const screening = document.querySelector('.film');
const template = document.querySelector('#movie-player');
function player() {
  let film = screening.querySelector('video');
  if (!film) {
    film = template.content.firstElementChild.cloneNode(true);
    screening.append(film);
    // The demo is silent. Expose its descriptive captions on first play.
    if (film.textTracks[0]) film.textTracks[0].mode = 'showing';
  }
  return film;
}
screening.querySelector('summary').addEventListener('click', () => {
  if (screening.open) {
    screening.querySelector('video')?.pause();
  } else {
    player().play().catch(() => { /* The native controls remain available. */ });
  }
});
screening.addEventListener('toggle', () => {
  if (screening.open) player();
  else screening.querySelector('video')?.pause();
});
