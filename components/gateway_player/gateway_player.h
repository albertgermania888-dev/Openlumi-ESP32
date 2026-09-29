#pragma once
#include "esphome.h"
#include "esphome/components/media_player/media_player.h"

namespace gateway_player {

class GatewayMediaPlayer : public media_player::MediaPlayer, public Component {
 public:
  void setup() override {
    this->state = media_player::MEDIA_PLAYER_STATE_IDLE;
  }

  media_player::MediaPlayerTraits get_traits() override {
    media_player::MediaPlayerTraits traits;
    traits.set_supports_pause(true);
    traits.set_supports_volume(true);
    return traits;
  }

  void control(const media_player::MediaPlayerCall &call) override {
    if (call.get_command().has_value()) {
      switch (call.get_command().value()) {
        case media_player::MEDIA_PLAYER_COMMAND_PLAY:
          Serial.printf("CMD:MPD:RESUME\n");
          this->state = media_player::MEDIA_PLAYER_STATE_PLAYING;
          break;
        case media_player::MEDIA_PLAYER_COMMAND_PAUSE:
          Serial.printf("CMD:MPD:PAUSE\n");
          this->state = media_player::MEDIA_PLAYER_STATE_PAUSED;
          break;
        case media_player::MEDIA_PLAYER_COMMAND_STOP:
          Serial.printf("CMD:MPD:STOP\n");
          this->state = media_player::MEDIA_PLAYER_STATE_IDLE;
          break;
        case media_player::MEDIA_PLAYER_COMMAND_TOGGLE:
          if (this->state == media_player::MEDIA_PLAYER_STATE_PLAYING) {
            Serial.printf("CMD:MPD:PAUSE\n");
            this->state = media_player::MEDIA_PLAYER_STATE_PAUSED;
          } else {
            Serial.printf("CMD:MPD:RESUME\n");
            this->state = media_player::MEDIA_PLAYER_STATE_PLAYING;
          }
          break;
      }
    }
    if (call.get_volume().has_value()) {
      float vol = call.get_volume().value();
      Serial.printf("CMD:MPD:VOL:%d\n", (int)(vol * 100));
      this->volume = vol;
    }
    if (call.get_media_url().has_value()) {
      std::string url = call.get_media_url().value();
      Serial.printf("CMD:MPD:PLAY:%s\n", url.c_str());
      this->state = media_player::MEDIA_PLAYER_STATE_PLAYING;
    }
    this->publish_state();
  }
};

}  // namespace gateway_player
