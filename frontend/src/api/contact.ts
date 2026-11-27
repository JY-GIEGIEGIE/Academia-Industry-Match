import type { Intent, IntentContact, IntentContactResponse } from '../types'

export function isContactRevealed(intent: Pick<Intent, 'status' | 'contact_revealed'>): boolean {
  return typeof intent.contact_revealed === 'boolean'
    ? intent.contact_revealed
    : intent.status === 'confirmed'
}

export function normalizeIntentContact(
  contact: IntentContactResponse | IntentContact,
): IntentContact {
  if ('contacts' in contact) return contact
  return {
    intent_id: contact.intent_id,
    is_simulated: true,
    contacts:
      'researcher_contact' in contact
        ? [
            { role: 'researcher', ...contact.researcher_contact },
            { role: 'enterprise', ...contact.enterprise_contact },
          ]
        : [{ email: contact.email, phone: contact.phone }],
  }
}
