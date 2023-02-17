# SmoothBrain

Version 0.1.1

SmoothBrain is an Anki plugin that gets your highlights from [Readwise][readwise]
and generates flashcards for them using [OpenAI's GPT API][openai].

## Setup

This plugin doesn't yet have a version on the Anki plugin server, so installation
needs to be completed manually.

1. Place the all files from this repository in a `smoothbrain` subfolder in your [Anki addons folder][anki_addons_folder].
2. Launch or restart Anki.
3. Go to the `Tools` menu at the top, then click `Add-ons`.
4. Find the entry for `smoothbrain`, select it, and click the `Config` button.
5. Get a [Readwise API key][readwise_api_key].
6. Get a [OpenAI API key][openai_api_key].
7. Enter your API keys in the config and click `OK`.
8. Restart Anki. <!-- TODO: test if I can bypass this by using a function to get the config -->

## Usage

1. Go to the `Tools` menu at the top and click `Sync Readwise`, or hit `CMD+R` on Mac (or `CTRL+R` on Windows or Linux).
2. Wait for a while... the UI freezing up with large collections is a known bug.
3. Review the cards! Suspend any that aren't good. In the future I'll set up a way to send me good/bad flashcards so I can fine-tune the model.

## Contributing

- Create a ticket on GitHub for bug reports and feature requests.
- Follow the [git-flow branching scheme][git-flow-instructions] (use the [git-flow CLI tool if you wish][git-flow-cli]).
- Bump the version using `bumpversion <major|minor|patch>`.
- Create a PR into `develop` and I'll merge your work in.

[readwise]: https://readwise.io
[openai]: https://openai.com
[readwise_api_key]: https://readwise.io/access_token
[openai_api_key]: https://beta.openai.com/account/api-keys
[anki_addons_folder]: https://addon-docs.ankiweb.net/addon-folders.html

[git-flow-instructions]: https://nvie.com/posts/a-successful-git-branching-model/
[git-flow-tool]: https://github.com/nvie/gitflow/tree/master