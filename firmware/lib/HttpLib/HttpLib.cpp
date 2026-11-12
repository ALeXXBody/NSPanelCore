#include <HTTPClient.h>
#include <HttpLib.hpp>
#include <MqttLog.hpp>
#include <cstdint>

size_t HttpLib::GetFileSize(const char *url) {
  HTTPClient httpClient;
  httpClient.begin(url);
  const char *header_names[] = {"Content-Length"};
  httpClient.collectHeaders(header_names, 1);
  int httpReturnCode = httpClient.GET();

  if (httpReturnCode != 200) {
    LOG_ERROR("Failed to retrive file size for URL '", url, "'. Got return code: ", httpReturnCode);
    httpClient.end();
    return 0;
  }

  try {
    size_t content_length = httpClient.header("Content-Length").toInt();
    httpClient.end();
    return content_length;
  } catch (...) {
    LOG_ERROR("Something went wrong when checking file size for URL '", url, "'.");
  }
  httpClient.end();
  return 0;
}

size_t HttpLib::DownloadChunk(uint8_t *buffer, const char *address, size_t offset, size_t size) {
  HTTPClient httpClient;
  httpClient.begin(address);
  httpClient.setTimeout(15000);

  std::string rangeHeader = "bytes=";
  rangeHeader.append(std::to_string(offset));
  rangeHeader.append("-");
  rangeHeader.append(std::to_string(offset + size - 1));
  httpClient.addHeader("Range", rangeHeader.c_str());
  rangeHeader.clear();

  int httpReturnCode = httpClient.GET();
  // LOG_TRACE("Downloading TFT ", rangeHeader.c_str(), " got return code: ", httpReturnCode);
  if (httpReturnCode != 200 && httpReturnCode != 206) {
    httpClient.end();
    LOG_ERROR("Failed to retrive file chunk from URL '", address, "'. Got return code: ", httpReturnCode);
    return 0;
  }

  // Read until the full chunk arrived or the stream stalls: a single
  // readBytes() may return a short count on a slow link, and the old code
  // treated that as the final size (corrupt flash at 100% progress).
  size_t sizeReceived = 0;
  unsigned long deadline = millis() + 15000;
  while (sizeReceived < size && (long)(deadline - millis()) > 0) {
    int avail = httpClient.getStreamPtr()->available();
    if (avail <= 0) {
      vTaskDelay(20 / portTICK_PERIOD_MS);
      continue;
    }
    size_t want = size - sizeReceived;
    if ((size_t)avail < want) {
      want = avail;
    }
    int got = httpClient.getStream().readBytes(&buffer[sizeReceived], want);
    if (got <= 0) {
      vTaskDelay(20 / portTICK_PERIOD_MS);
      continue;
    }
    sizeReceived += got;
  }
  httpClient.end();

  return sizeReceived;
}

bool HttpLib::GetMD5sum(const char *address, char *buffer) {
  HTTPClient http;
  http.begin(address);
  int responseCode = http.GET();

  if (responseCode == 200) {
    http.getString().toCharArray(buffer, 33);
    http.end();
    return true;
  }
  http.end();
  return false;
}

bool HttpLib::DownloadJSON(const char *address, JsonDocument *document) {
  HTTPClient http;
  http.begin(address);
  int responseCode = http.GET();

  if (responseCode == 200) {
    DeserializationError error = deserializeJson(*document, http.getStream());
    http.end();
    return !error; // Return true or false depending on there was a deserialization error
  }
  http.end();
  return false;
}
