/* P216: POST /provision — body: JSON {"mqtt_server":"..","mqtt_port":N,
 * "mqtt_user":"..","mqtt_pass":".."}. Validates, saves, reboots into MQTT.
 * The manager calls this after the user accepts the panel in the app. */
#include "esp_http_server.h"
#include "provision.h"
#include "form_parse.h"
#include "config.h"
#include <string>
#include <map>
#include <cstdlib>
#include <cstring>

extern void nsp_web_log(const std::string &line);
extern void nsp_mqtt_publish_log(const char *msg);

/* P222c: the field extraction moved to provision_parse.cpp — pure,
 * host-unit-tested (the /provision endpoint shipped without tests once;
 * never again). */
#include "provision_parse.h"

esp_err_t nsp_handle_provision(httpd_req_t *req) {
    /* P279 HIGH fix: /provision had NO CSRF guard — a cross-site POST
     * re-provisioned the panel to an attacker's broker, whose
     * register_accept then pointed the self-driven OTA at attacker
     * firmware. Same X-NSPanel check as /save and /action. */
    {
        extern bool nsp_web_post_ok(httpd_req_t *req);
        if (!nsp_web_post_ok(req)) {
            httpd_resp_send_err(req, HTTPD_403_FORBIDDEN, "Forbidden");
            return ESP_OK;
        }
    }
    if (req->content_len <= 0 || req->content_len > 2048) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Bad body");
        return ESP_OK;
    }
    char buf[2048] = "";
    int r = httpd_req_recv(req, buf, req->content_len);
    if (r <= 0) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "No body");
        return ESP_OK;
    }
    std::string body(buf, r);
    std::string server, port, user, pass;
    if (!nsp_provision_field(body, "mqtt_server", server) || server.empty()) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "mqtt_server missing");
        return ESP_OK;
    }
    nsp_provision_field(body, "mqtt_port", port);
    nsp_provision_field(body, "mqtt_user", user);
    nsp_provision_field(body, "mqtt_pass", pass);

    g_cfg.mqtt_server = server;
    {
        int p = atoi(port.c_str());
        if (p > 0 && p < 65536) g_cfg.mqtt_port = p;
    }
    g_cfg.mqtt_user = user;
    g_cfg.mqtt_pass = pass;
    nsp_config_save();

    {
        char l[128];
        snprintf(l, sizeof(l), "provisioned: mqtt %s:%d — rebooting into the broker",
                 server.c_str(), g_cfg.mqtt_port);
        nsp_web_log(l);
        nsp_mqtt_publish_log(l);
    }
    httpd_resp_set_type(req, "text/plain");
    const char *ok = "provisioned — rebooting";
    httpd_resp_send(req, ok, strlen(ok));
    vTaskDelay(pdMS_TO_TICKS(1200));
    esp_restart();
    return ESP_OK;
}
