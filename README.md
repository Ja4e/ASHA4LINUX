# ASHA 4 linux
Program for streaming ASHA hearing aids

Supports other ASHA devices for volume control with provided bash script (volume.sh)

TODO:
improve the wiki

I need to make an automatic delay based on the continous polling where it was getting packetloss exits seems quite uhm predictable for SBC codec where the some SBC hearing aid as secondary devices aggressively starts at very low latency before there is packet loss and jumping to different buffer/latency values. Vary annoying.
