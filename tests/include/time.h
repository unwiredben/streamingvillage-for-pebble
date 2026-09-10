#pragma once
// Pebble declares its own struct tm and time functions in pebble.h.
// Supply only the host time_t here to avoid glibc's competing struct tm.
#include <sys/types.h>
