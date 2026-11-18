/* P216: the provisioning endpoint — the app pushes the MQTT settings to the
 * panel over HTTP after the user accepts it in the manager. Zero typing. */
#pragma once
#include "esp_http_server.h"

esp_err_t nsp_handle_provision(httpd_req_t *req);
