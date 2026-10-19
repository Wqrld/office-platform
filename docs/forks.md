# Forks

Four apps run from our forks under `github.com/Wqrld`. In each case the fork's git tag pins
both the chart and the images, so going back to upstream means changing a url. The details
are in each app's README, under Pins and Upstream PRs.

| App | Why we fork | Back to upstream when |
|---|---|---|
| Drive | Document thumbnails, rendered by Collabora | Upstream releases the thumbnails feature |
| Calendars | The chart is ours, and upstream's images lack the health endpoints the chart probes, and don't run as non-root | The chart PR lands, in a release with the image fixes |
| Projects | Upstream ships no chart. The image has two fixes: a path check on public files, and a numeric user | The PR lands, and upstream releases both image fixes |
| Messages | Upstream ships no chart, and doesn't publish the spam filter (MPA) image. Plus three MPA and MTA fixes | The PR lands, and upstream publishes the MPA image |

No PR links are recorded yet; add each one to its row when it is opened.

Two sources are not forks but pin a commit, because upstream has no tag to pin: **Find**
has never cut a release, and **LiveKit**'s chart index stopped updating in mid-2025.
`charts/control-plane/templates/sources.yaml` explains both.

Check this table on every upstream bump.
