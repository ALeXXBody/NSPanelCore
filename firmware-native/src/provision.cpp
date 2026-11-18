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

static bool json_str(const std::string &body, const char *key, std::string &out) {
    /* tolerant parse: "key":"value" or "key":value (numbers) */
    std::string needle = std::string("\"") + key + "\"";
    size_t k = body.find(needle);
    if (k == std::string::npos) return false;
    size_t colon = body.find(':', k + needle.size());
    if (colon == std::string::npos) return false;
    size_t q1 = body.find('"', colon + 1);
    if (q1 != std::string::npos && q1 < colon + 12) {
        size_t q2 = body.find('"', q1 + 1);
        if (q2 == std::string::npos) return false;
        out = body.substr(q1 + 1, q2 - q1 - 1);
        return true;
    }
    /* numeric */
    size_t end = body.find_first_not_of("0123456789", colon + 1);
    if (end == std::string::npos) end = body.size();
    out = body.substr(body.find_first_of("0123456789-", colon + 1),
                      end - body.find_first_of("0123456789-", colon + 1));
    return true;
}

esp_err_t nsp_handle_provision(httpd_req_t *req) {
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
    if (!json_str(body, "mqtt_server", server) || server.empty()) {
        httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "mqtt_server missing");
        return ESP_OK;
    }
    json_str(body, "mqtt_port", port);
    json_str(body, "mqtt_user", user);
    json_str(body, "mqtt_pass", pass);

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
