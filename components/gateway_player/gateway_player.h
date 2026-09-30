#pragma once
#include "esphome.h"
#include "esphome/components/media_player/media_player.h"

namespace esphome {
namespace gateway_player {

class GatewayMediaPlayer : public esphome::media_player::MediaPlayer, public esphome::Component {
 public:
  void setup() override {
    this->state = esphome::media_player::MEDIA_PLAYER_STATE_IDLE;
  }

  esphome::media_player::MediaPlayerTraits get_traits() override {
    esphome::media_player::MediaPlayerTraits traits;
    traits.set_supports_pause(true);
    return traits;
  }

  void control(const esphome::media_player::MediaPlayerCall &call) override {
    if (call.get_command().has_value()) {
      auto cmd = call.get_command().value();
      
      if (cmd == esphome::media_player::MEDIA_PLAYER_COMMAND_PLAY) {
        Serial.printf("CMD:MPD:RESUME\n");
        this->state = esphome::media_player::MEDIA_PLAYER_STATE_PLAYING;
      } 
      else if (cmd == esphome::media_player::MEDIA_PLAYER_COMMAND_PAUSE) {
        Serial.printf("CMD:MPD:PAUSE\n");
        this->state = esphome::media_player::MEDIA_PLAYER_STATE_PAUSED;
      } 
      else if (cmd == esphome::media_player::MEDIA_PLAYER_COMMAND_STOP) {
        Serial.printf("CMD:MPD:STOP\n");
        this->state = esphome::media_player::MEDIA_PLAYER_STATE_IDLE;
      } 
      else if (cmd == esphome::media_player::MEDIA_PLAYER_COMMAND_TOGGLE) {
        if (this->state == esphome::media_player::MEDIA_PLAYER_STATE_PLAYING) {
          Serial.printf("CMD:MPD:PAUSE\n");
          this->state = esphome::media_player::MEDIA_PLAYER_STATE_PAUSED;
        } else {
          Serial.printf("CMD:MPD:RESUME\n");
          this->state = esphome::media_player::MEDIA_PLAYER_STATE_PLAYING;
        }
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
      this->state = esphome::media_player::MEDIA_PLAYER_STATE_PLAYING;
    }
    
    this->publish_state();
  }
};

}  // namespace gateway_player
}  // namespace esphome
