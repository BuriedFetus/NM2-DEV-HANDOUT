CFLAGS = -std=c99 -Wall -Wextra -Wconversion -O2

test: test_ratchet
	./test_ratchet ../..

test_ratchet: test_ratchet.c ratchet.c ratchet.h
	$(CC) $(CFLAGS) -o $@ test_ratchet.c ratchet.c

clean:
	rm -f test_ratchet

.PHONY: test clean
