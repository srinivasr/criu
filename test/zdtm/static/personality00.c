#include <errno.h>
#include <sys/personality.h>

#include "zdtmtst.h"

const char *test_doc = "Check that the ADDR_NO_RANDOMIZE personality bit is preserved across C/R";
const char *test_author = "srinivasr <sriniv4sreddy@gmail.com>";

int main(int argc, char **argv)
{
	int persona, after;
	int ret;

	test_init(argc, argv);

	persona = personality(0xffffffff);
	if (persona < 0) {
		fail("can't read personality");
		return 1;
	}

	ret = personality(persona | ADDR_NO_RANDOMIZE);
	if (ret < 0) {
		fail("can't set ADDR_NO_RANDOMIZE");
		return 1;
	}

	test_daemon();
	test_waitsig();

	after = personality(0xffffffff);
	if (after < 0) {
		fail("can't read restored personality");
		return 1;
	}

	if (after & ADDR_NO_RANDOMIZE)
		pass();
	else
		fail("personality lost: before=0x%x after=0x%x", persona | ADDR_NO_RANDOMIZE, after);

	return 0;
}
