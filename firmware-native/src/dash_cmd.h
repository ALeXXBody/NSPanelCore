/* NSPanel Core — dash command parse (pure, host-testable). */
#pragma once

#include <string>

/* {"command":"dash","payload":"<statement>"} → 0 + sanitized statement
 * in |stmt| ("" on failure). -1 = rejected. */
int nsp_dash_parse(const std::string &payload, std::string &stmt);

/* {"command":"dash_map","pages":[...]} → the count written into |pages|
 * (up to |max| ids, each 0..15), or -1 = rejected. */
int nsp_dash_map_parse(const std::string &payload, int *pages, int max);

/* Is |page| one of the dash pages? */
bool nsp_dash_page(const int *pages, int count, int page);

/* Runtime state: store/clear the dash page-id map (RAM only; the
 * manager re-pushes it on every register), and the touch-handler check. */
bool nsp_dash_map_apply(const std::string &payload);
void nsp_dash_map_clear(void);
bool nsp_dash_is_dash_page(int page);
/* P269: the dash pages in the manager's order — the swipe navigates them. */
int nsp_dash_page_count(void);
int nsp_dash_page_id(int index);
int nsp_dash_page_index(int page);
