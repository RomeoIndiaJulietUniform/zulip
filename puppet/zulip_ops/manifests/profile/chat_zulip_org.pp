class zulip_ops::profile::chat_zulip_org inherits zulip_ops::profile::base {
  include zulip::profile::standalone
  include zulip::postfix_localmail
  include zulip::hooks::sentry

  include zulip_ops::app_frontend_monitoring
  include zulip_ops::prometheus::redis
  include zulip_ops::prometheus::postgresql
  zulip_ops::firewall_allow { 'smokescreen_metrics': port => '9810' }
  zulip_ops::firewall_allow { 'http': }
  zulip_ops::firewall_allow { 'https': }
  zulip_ops::firewall_allow { 'smtp': }

  Zulip_Ops::User_Dotfiles['root'] {
    keys => false,
  }
  Zulip_Ops::User_Dotfiles['zulip'] {
    keys => false,
  }
}
